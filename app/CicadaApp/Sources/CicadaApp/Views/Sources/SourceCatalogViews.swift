import SwiftUI

// G217 (ruling 36 D6) — the Sources page as the one catalogue: rows grouped by way in, each a logo tile, a name and a
// dot with one word (DR-34 row heights, DR-38 nothing said twice, DR-52 via the one tile adapter, DR-74 the detail's
// head). The old Integrations page's rows and the "Add a source" grid both land here.

/// G217 — the Sources page reads and writes the per-site reading switch through Settings' own model
/// (`ReadingAgentModel`, in memory, not a Store domain), so the first-use consent is the same: a site turns on in one
/// call only when a current acknowledgement is stored; otherwise the versioned first-use sheet asks first, and only
/// its "Turn on" sends the acknowledgement (review of #428).
extension ReadingAgentModel {
    /// The walled sites an agent may read now: none while agent reading is off.
    var readableSites: Set<String> {
        guard let settings, settings.agentEnabled else { return [] }
        return Set(settings.allowedSites.keys)
    }

    /// G206 — the saved lists the person's agent keeps current: none while agent reading is off.
    var savedListsOn: Set<String> {
        guard let settings, settings.agentEnabled else { return [] }
        // 2026-10-26: a YouTube list kept current reads as "youtube" (the YouTube row's Connected).
        let youtube = settings.youtubeLists.watchLater || settings.youtubeLists.history
        // G89: a Substack list kept current reads as "substack" (the Substack row's Connected).
        let substack = settings.substackLists.values.contains(true)
        return Set(settings.savedLists.filter { $0.value }.map { $0.key } + (youtube ? ["youtube"] : [])
                   + (substack ? [SourceCatalog.substackId] : []))
    }
}

/// 2026-10-23 — which of this Mac's readers are on, for `SourceCatalog.status`. The backend knows a reader synced once,
/// never that it was disconnected here (the flags are this Mac's), so a Calendar, Contacts, tab groups, YouTube history
/// or a browser's bookmark watch turned off kept reading Connected while nothing more arrived. Each observable value is
/// read so the row redraws when it flips. Messages and Wispr Flow are answered by the backend (their switches live in
/// the bank's settings).
@MainActor
enum LocalReaders {
    static func on(calendar: CalendarReader?, contacts: ContactsReader?, tabGroups: TabGroupWatcher?,
                   watchHistory: WatchHistoryWatcher?, browsers: BrowserWatcher?,
                   notes: AppleNotesWatcher?, traces: TraceRecorder? = nil,
                   reminders: RemindersReader? = nil) -> [String: Bool] {
        var on: [String: Bool] = [:]
        // G218 — the recorder's own state: Connected only while it records.
        if let traces { on[SourceCatalog.tracesId] = traces.isRecording }
        // G219: on only while connected with at least one list ticked — nothing arrives otherwise.
        if let reminders { on[RemindersReader.channel] = reminders.isOn }
        if let calendar { on[CalendarRow.channelId] = calendarOn(calendar.status) }
        // 2026-11-04 — on means allowed AND turned on: a reader whose access was taken away reads Off, never Connected.
        if let contacts { on[ContactsReader.channel] = contactsOn(enabled: contacts.enabled, status: contacts.status) }
        if let tabGroups { on[TabGroupWatcher.channel] = tabGroups.enabled }
        if let watchHistory { on[WatchHistoryWatcher.channel] = watchHistory.enabled }
        if let notes { on[AppleNotesWatcher.channel] = notes.enabled }
        if let browsers {
            for (channel, _) in BrowserWatchPolicy.watched {
                _ = browsers.states[channel]
                on[channel] = browsers.isEnabled(channel)
            }
        }
        return on
    }

    /// Looks pass 2 (2026-10-23) — Calendar's head and its row read one value: the reader's own status, the one the
    /// row's line and buttons already follow (`CalendarRowText`). The head read `isEnabled` (a defaults flag, not
    /// observed) beside it, so the two could say Connected and "Not connected" at once. Off and denied are off;
    /// syncing, synced and a failed read are a connected reader (a failure says why in the row's line).
    nonisolated static func contactsOn(enabled: Bool, status: ContactsReader.Status) -> Bool {
        // `.off` is also the reader's state before `start()` ran at launch: the turned-on switch is what counts then.
        enabled && status != .denied
    }

    nonisolated static func calendarOn(_ status: CalendarReader.Status) -> Bool {
        switch status {
        case .off, .denied: false
        case .syncing, .synced, .failed: true
        }
    }
}

/// Looks pass 2 (2026-10-23) — set by a source's detail, whose head already shows the source's mark and name: the
/// source's own row inside it (`CalendarRow`, `ContactsRow`, `MessagesRow`, `WisprFlowRow`, a browser's row) then
/// draws only its line and its buttons, never a second, smaller mark and the same name again (DR-38, DR-52).
private struct SourceDetailHeadShownKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var sourceDetailHeadShown: Bool {
        get { self[SourceDetailHeadShownKey.self] }
        set { self[SourceDetailHeadShownKey.self] = newValue }
    }
}

/// One catalogue row: tile · name (and when it last synced, only when on) · dot + one word. An Off row's word is its
/// verb as a neutral button would be too loud in a list of twenty, so the row opens the detail, where the verb is.
struct SourceCatalogRowView: View {
    let row: SourceCatalogRow
    let style: ColumnPlan.ListStyle
    let selected: Bool
    let now: Date
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                // Looks pass 2 (2026-10-23): one tile size for a two-line row, at the root and beside an open source
                // alike (the list beside a detail drew 24 pt while the root, the detail head and onboarding drew 36);
                // only the title-only row (36 pt tall, DR-34) keeps the dense tile.
                SourceLogoTile(origin: row.entry.origin, size: SourceCatalogRowView.tileSize(style))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(row.entry.title)
                        .font(CicadaTheme.font(size: 13, weight: selected || style == .wide ? .medium : .regular))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if style != .titles, style != .hidden, let line = SourceCatalog.line(row, now: now) {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)   // DR-36
                Spacer(minLength: CicadaTheme.spacingSM)
                if style == .wide || style == .triage {
                    StatusWord(word: row.status.word, tone: row.status.tone)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: style == .titles || style == .hidden ? RowMetrics.titleOnly : RowMetrics.twoLine,
                        selected: selected)
        .accessibilityLabel("\(row.entry.title), \(row.status.word)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    /// The tile a row wears: the detail head's and onboarding's 36 pt on every two-line row, 24 pt on a title-only row.
    static func tileSize(_ style: ColumnPlan.ListStyle) -> SourceLogoTile.Size {
        switch style {
        case .wide, .triage: .row
        case .titles, .hidden: .dense
        }
    }
}

/// The groups as labelled rows (DR-47), one rendering for the root and the list beside an open source.
struct SourceCatalogList: View {
    let rows: [SourceCatalogRow]
    let style: ColumnPlan.ListStyle
    var selection: SourcesSelection? = nil
    let open: (SourcesSelection) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                ForEach(Array(SourceCatalog.grouped(rows).enumerated()), id: \.element.group) { index, group in
                    SectionLabel(group.group.title)
                        .padding(.horizontal, CicadaTheme.scaled(10))
                        .padding(.top, index == 0 ? 0 : CicadaTheme.scaled(14))
                        .padding(.bottom, CicadaTheme.scaled(4))
                    ForEach(group.rows) { row in
                        SourceCatalogRowView(row: row, style: style, selected: selection == .entry(row.id),
                                             now: context.date) { open(.entry(row.id)) }
                            .id(SourcesSelection.entry(row.id))
                    }
                }
            }
        }
    }
}

/// One way in, opened: the head (tile, name, dot + word), the source's own control (the same rows Settings drew,
/// so nothing a person set moves), per-site reading for an account read in the browser, then what came in.
struct SourceCatalogDetail: View {
    let row: SourceCatalogRow
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(ReadingAgentModel.self) private var reading
    /// The site whose switch raised the first-use sheet (acknowledgement not current).
    @State private var consentSite: String?
    /// Whether that switch was the site's saved list (G206), so the sheet turns on the list, never the site.
    @State private var consentSavedList = false
    /// 2026-10-26 — the YouTube list whose switch raised the first-use sheet.
    @State private var consentYouTube: YouTubeList?
    /// G89 — the Substack list whose switch raised the first-use sheet.
    @State private var consentSubstack: SubstackList?
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var flowTile: AddSourceTile?
    /// The connector panel's export walkthrough binding; a tier-2 connector has no export walkthrough.
    @State private var vendor: WalkthroughVendor = .claude
    @State private var browsers = BrowserInventory.empty
    /// G218 (owner 2026-10-26) — the Traces page is on the rail.
    @AppStorage(TracesPageVisibility.key) private var tracesPage = false
    /// source-page-v3 — the page's one search, and which of its lists fills the column instead of the page.
    @State private var query = ""
    @State private var drill: SourceDrill?
    @Environment(ChannelItemsCache.self) private var itemsCache: ChannelItemsCache?
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(SyncActivity.self) private var activity: SyncActivity?
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(WhatsAppWatcher.self) private var whatsApp: WhatsAppWatcher?
    @Environment(MessagesWatcher.self) private var messagesWatcher: MessagesWatcher?
    @Environment(ExploreCache.self) private var exploreCache
    @State private var showReadingSheet = false
    @State private var showExploreSheet = false
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(WatchHistoryWatcher.self) private var watchHistory: WatchHistoryWatcher?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(ContactsReader.self) private var contacts: ContactsReader?
    @Environment(RemindersReader.self) private var remindersReader: RemindersReader?
    @Environment(IntakeRouter.self) private var intake
    /// What the footer's last Refresh said.
    @State private var feedNote: String?

    private var channels: [SourceChannel] { store.channels.value ?? [] }

    // MARK: - source-page-v3: what the template reads

    /// The lists this page shows: the overview row's own list (Messages by chat, watched days, a saved source's saves,
    /// a harness's conversations), else each connected channel's.
    private var listChannels: [(id: String, label: String?)] {
        // 2026-11-04 — every list the entry holds, each its own labelled section (YouTube: History, then Saved), where
        // the page showed only the first overview row's list.
        let rows = overviewRows
        if let overview, overview.kind == .harness { return [] }
        if !rows.isEmpty {
            return rows.map { ($0.itemsListId, rows.count > 1 ? SourceSectionTitle.of($0) : nil) }
        }
        let on = mine.filter(\.connected)
        return on.map { ($0.id, on.count > 1 ? $0.label : nil) }
    }

    /// Every overview row this entry speaks for, once per list, in the entry's own channel order.
    private var overviewRows: [SourceOverview] {
        guard let overview else { return [] }
        if overview.kind == .harness || row.entry.overviewId != nil || row.entry.id == "folders" { return [overview] }
        let all = store.sourcesOverview.value ?? []
        var seen = Set<String>()
        var out: [SourceOverview] = []
        for channel in row.entry.channels {
            for item in all where item.kind != .harness && (item.id == channel || item.channelId == channel) {
                if seen.insert(item.itemsListId).inserted { out.append(item) }
            }
        }
        return out.isEmpty ? [overview] : out
    }

    private var savedStyle: Bool { overview?.intent == .saved }

    /// The status: the catalogue's word, the first channel's run (a read in progress, a failure, missing access) and
    /// the day the newest item came in — or, for a chat reader on this Mac, when it last checked the ticked chats and
    /// the newest message in them (2026-11-03, `ChatCheck`).
    private var pageStatus: SourcePageStatus {
        let channel = mine.first
        let watch = channel.flatMap { watcher.state(for: $0.id) }
        let run = SourceRowText.status(channel: channel, watch: watch, run: channel.flatMap { activity?.run(for: $0.id) })
        return SourcePageStatus.of(row: row.status, run: run, latest: latest, check: chatCheck,
                                   notInstalled: row.notInstalled)
    }

    private var chatCheck: ChatCheck? {
        switch row.entry.id {
        case WhatsAppWatcher.channel: whatsApp?.check
        case MessagesWatcher.channel: messagesWatcher?.check
        default: nil
        }
    }

    private var latest: String? {
        if let overview, overview.kind == .harness {
            return overview.lastActivityDate.map { ISODay.today(now: $0).description }
        }
        return listChannels.compactMap { itemsCache?.list($0.id)?.latest }.max()
    }

    /// 2026-11-03 (owner: "this of what cicada reads in all pages i see it unnecessary") — the "What Cicada reads" sheet
    /// is gone from every source page. What a chat reader's "checked" measures stays on the status line's hover only.
    private var statusHelp: String? {
        switch row.entry.id {
        case MessagesWatcher.channel: Copy.Messages.whenItReads
        case WhatsAppWatcher.channel: Copy.Chats.whatsAppWhenItReads
        default: row.status == .waitingForAgent ? Copy.Catalog.waitingForAgentHelp : nil
        }
    }

    private func takeConversationQuery() {
        guard overview?.kind == .harness, let q = router.consumeConversationQuery() else { return }
        drill = nil
        query = q
    }

    private func removalsEmpty(_ overview: SourceOverview) -> Bool {
        guard let id = overview.channelId else { return true }
        return InboxItem.openRemovals(in: store.visibleInbox, channelId: id).isEmpty
            && inboxVM.heldRemoval(channel: id) == nil
    }

    /// The total the search's prompt names: the channel's whole count when the backend sent it.
    private var searchPrompt: String {
        guard let first = listChannels.first else { return Copy.SourcePage.searchPrompt(total: nil, noun: ("item", "items")) }
        let list = itemsCache?.list(first.id)
        // The prompt names the rows the list draws: chats, days, else the channel's own noun.
        let noun: (one: String, many: String) = switch list?.items.first {
        case let item? where item.kind == .chat: ("chat", "chats")
        case let item? where item.videos != nil: ("day", "days")
        default: CapturedItems.noun(channel: first.id, countNoun: channels.first { $0.id == first.id }?.countNoun)
        }
        let total = listChannels.count == 1 ? (list?.all ?? list?.total) : nil
        return Copy.SourcePage.searchPrompt(total: total, noun: noun)
    }
    private var mine: [SourceChannel] { SourceCatalog.channelsOf(row.entry, in: channels) }
    private var overview: SourceOverview? {
        SourceCatalog.overviewRow(for: row.entry, in: store.sourcesOverview.value ?? [])
    }

    var body: some View {
        // GitHub draws its own page on the same layout: its status comes from its sign-in, not the catalogue alone.
        if row.entry.id == "github" {
            GitHubSourcePage(row: row, backLabel: hiddenListCount.map { Copy.Lists.sourcesBack($0) },
                             onShowList: onShowList, onClose: onClose)
        } else {
            page
        }
    }

    /// The standard source page (owner 2026-11-04; `SourcePageLayout`): head, connect area, content, footer.
    private var page: some View {
        SourcePageLayout(title: row.entry.title, origin: row.entry.origin, status: pageStatus, statusHelp: statusHelp,
                         backLabel: hiddenListCount.map { Copy.Lists.sourcesBack($0) }, onShowList: onShowList,
                         onClose: onClose) {
            if drill == nil { connectSlot }
        } content: {
            if let drill {
                drilled(drill)
            } else {
                if let overview, overview.kind != .harness, !removalsEmpty(overview) {
                    ChannelRemovals(source: overview)
                }
                contentSlot
            }
        } footer: {
            if drill == nil { footerSlot }
        }
        .sheet(item: $flowTile) { tile in
            AddSourceSheet(initialTile: tile, onClose: { flowTile = nil }, flowOnly: true)
        }
        .sheet(isPresented: $showReadingSheet, onDismiss: { Task { await reading.load() } }) {
            ReadingInBrowserSheet { showReadingSheet = false }
        }
        .sheet(isPresented: $showExploreSheet) {
            ExploreSheet { showExploreSheet = false }
        }
        .sourcePageBack(active: drill != nil) { drill = nil }
        .task { await reading.loadSettings() }
        // G136 R-SU18 — a palette conversation row lands on its agent's page with the search filled.
        .onAppear { takeConversationQuery() }
        .onChange(of: router.pendingConversationQuery) { _, _ in takeConversationQuery() }
        .sheet(item: $consentSubstack) { list in
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consentSubstack = nil }) {
                ReadingFirstUseSheet(model: reading, site: nil, label: nil, substackList: list) { consentSubstack = nil }
            }
        }
        .sheet(item: $consentYouTube) { list in
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consentYouTube = nil }) {
                ReadingFirstUseSheet(model: reading, site: nil, label: nil, youtubeList: list) { consentYouTube = nil }
            }
        }
        .sheet(isPresented: Binding(get: { consentSite != nil }, set: { if !$0 { consentSite = nil } })) {
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consentSite = nil }) {
                ReadingFirstUseSheet(model: reading, site: consentSite, label: row.entry.title,
                                     savedList: consentSavedList) { consentSite = nil }
            }
        }
        .task {
            if row.entry.id.hasPrefix(SourceCatalog.browserPrefix) {
                browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value
            }
        }
    }

    // MARK: - The connect area

    /// The connect area, by source: one primary and at most one line for its state, then its ways in.
    @ViewBuilder
    private var connectSlot: some View {
        let entry = row.entry
        switch entry.id {
        case CalendarRow.channelId:
            CalendarSlot(slot: .connect)
        case ContactsReader.channel: ContactsSlot(slot: .connect)
        case RemindersReader.channel: RemindersSlot(slot: .connect)
        case AppleBooksReader.channel: AppleBooksSlot(slot: .connect, channel: mine.first)
        case "goodreads": GoodreadsSlot()
        case "book-scan": SourceConnectLine(text: Copy.bookScansLine)
        case MessagesWatcher.channel: ChatPickerSlot(slot: .connect, kind: .messages)
        case WhatsAppWatcher.channel: ChatPickerSlot(slot: .connect, kind: .whatsApp)
        case TelegramChats.channel: TelegramSlot(slot: .connect)
        case AppleNotesWatcher.channel: NotesSlot(slot: .connect)
        case LocalSourceWatcher.wisprChannel: WisprSlot(slot: .connect, notInstalled: row.notInstalled)
        case "folders": FolderSlot(slot: .connect, meetings: nil, hasFolders: !mine.isEmpty)
        case SourceCatalog.hexId: FolderSlot(slot: .connect, meetings: SourceCatalog.hexId, hasFolders: !mine.isEmpty)
        case SourceCatalog.meetingFoldersId: FolderSlot(slot: .connect, meetings: "", hasFolders: !mine.isEmpty)
        case SourceCatalog.tracesId:
            // Owner 2026-10-26 — once traces were ever on they have their own page; Sources keeps a link to it.
            if tracesPage { TracesSourcesLink() } else { TracesControls() }
        case "youtube":
            SourceConnectArea(ways: youtubeWays) { WatchHistoryState() }
        case SourceCatalog.substackId:
            // G89 — the three lists the person's own agent keeps current, as switches; how many publications the
            // person follows is the area's one line.
            SourceConnectArea(line: substackFollowing, ways: substackWays)
        case "spotify", "files":
            // Nothing in yet: the export's own drop, its where-from on hover — the source's mark on a file, never the
            // chat vendors'. Once something came in, the next import is one quiet way row above the list.
            if row.status == .off {
                IntakePanel(origin: .emptyState(.sources), compact: true, mark: entry.origin,
                            how: SourceCatalog.exportHow(entry.id))
            } else {
                SourceConnectArea(ways: [.importFile(origin: entry.origin, help: SourceCatalog.exportHow(entry.id)) {
                    chooseExport()
                }])
            }
        case "chat-exports":
            // A chat export is the chat vendors' own file: their marks are the right ones here. Each app's "request
            // your export" is a way in (its export page; its steps on hover). The reminder menu stays in the window's
            // intake overlay and Getting started: a menu of delays is not a switch or a button.
            IntakePanel(origin: .emptyState(.sources), compact: true, how: SourceCatalog.exportHow(entry.id))
            SourceConnectArea(ways: ChatVendor.allCases.map(ChatExportWay.of))
        case "notion":
            // The live connection is the primary; the export is one more way in, the file chooser of the one intake.
            let export = SourceWayIn.importFile(origin: entry.origin, help: Copy.Catalog.notionHow) { chooseExport() }
            if let api = channels.first(where: { $0.id == "notion-api" }) {
                ConnectorSlot(slot: .connect, channel: api, title: "Notion", ways: [export],
                              needsSignIn: row.status == .needsSignIn)
            } else {
                SourceConnectArea(ways: [export])
            }
        case "telegram":
            // The bot feed needs a public address Cicada never opens: its steps are one click away.
            SourceConnectArea(primary: entry.tile.map { tile in
                SourcePrimaryAction(title: Copy.Catalog.howToSetUp, help: Copy.Catalog.telegramHonest) {
                    flowTile = tile
                }
            })
        default:
            if entry.id.hasPrefix(SourceCatalog.browserPrefix) {
                let mine = BrowserInventory(installed: browsers.installed.filter {
                    SourceCatalog.browserPrefix + $0.id == entry.id
                })
                if let spec = mine.installed.first { BrowserWays(spec: spec, inventory: mine) }
            } else if entry.overviewId != nil {
                EmptyView()
            } else if let connector = Self.connectorChannel(in: mine) {
                ConnectorSlot(slot: .connect, channel: connector, title: entry.title, ways: siteWays,
                              vendors: entry.tile?.vendors ?? [], needsSignIn: row.status == .needsSignIn)
            } else if entry.site != nil || entry.verb == .importFile {
                SourceConnectArea(ways: siteWays)
            } else if let feed = mine.first, feed.actions.contains("manage"), let tile = entry.tile {
                // A feed: the Subscribe field and the list are its flow.
                if feed.count == 0 {
                    SourceConnectArea(primary: SourcePrimaryAction(title: verbTitle(entry.verb)) { flowTile = tile },
                                      line: feed.lastError)
                } else if let error = feed.lastError, !error.isEmpty {
                    SourceConnectLine(text: error, isAttention: true)
                }
            } else if let tile = entry.tile, row.status == .off {
                SourceConnectArea(primary: SourcePrimaryAction(title: verbTitle(entry.verb)) { flowTile = tile })
            }
        }
    }

    /// The one intake's file chooser; what it reads runs in the window's intake overlay, as a drop would.
    private func chooseExport() {
        let urls = IntakePicker.choose()
        guard !urls.isEmpty else { return }
        intake.accept(urls: urls, from: .emptyState(.sources))
    }

    /// An account's ways in beyond its connector: the browser reader's per-site switch, the saved list it keeps
    /// current, and the export (the source's own mark on a file, its where-from on hover).
    private var siteWays: [SourceWayIn] {
        var ways: [SourceWayIn] = []
        if let site = row.entry.site {
            ways.append(.browser(on: reading.readableSites.contains(site)) { flip(site, on: $0) })
            if SourceCatalog.savedListSites.contains(site) {
                ways.append(SourceWayIn(id: "saved", icon: .symbol("bookmark"), title: Copy.SourceLayout.savedList,
                                        control: .toggle(reading.savedListsOn.contains(site)) { flipSavedList(site, on: $0) },
                                        help: Copy.Catalog.readSavedList(site)))
            }
        }
        if let tile = row.entry.tile, row.entry.verb == .importFile || row.entry.site != nil {
            ways.append(.importFile(origin: row.entry.origin, help: SourceCatalog.exportHow(row.entry.id)) {
                flowTile = tile
            })
        }
        return ways
    }

    /// YouTube's ways in: the history Chrome keeps on this Mac, the two lists the person's agent keeps current, and
    /// the Takeout file.
    private var youtubeWays: [SourceWayIn] {
        var ways: [SourceWayIn] = []
        if let history = watchHistory {
            ways.append(SourceWayIn(id: "chrome", icon: .mark("chrome-bookmark"), title: Copy.SourceLayout.historyInChrome,
                                    control: .toggle(history.enabled) { on in
                                        if on { Task { await history.enable() } } else { history.disable() }
                                    },
                                    help: Copy.watchHistoryOffLine))
        }
        for list in YouTubeList.allCases {
            let on = reading.enabled && (reading.settings?.youtubeLists.isOn(list) ?? false)
            ways.append(SourceWayIn(id: "list-\(list.id)", icon: .symbol("globe"), title: Copy.SourceLayout.youtubeList(list),
                                    control: .toggle(on) { flipYouTube(list, on: $0) },
                                    help: YouTubeListWords.detail(list, on: on, status: reading.settings?.youtube)))
        }
        if let tile = row.entry.tile {
            ways.append(.importFile(origin: row.entry.origin, help: SourceCatalog.exportHow("youtube")) {
                flowTile = tile
            })
        }
        return ways
    }

    /// G89 — Substack's three lists (Saved, History, Subscriptions), each the switch its own agent keeps current; the
    /// first-use sheet first while agent reading is not yet on (`flipSubstack`). What each reads is its hover; why it
    /// goes through the person's own agent (Substack offers readers no connection) is every switch's hover too.
    private var substackWays: [SourceWayIn] {
        Self.substackWays(isOn: { reading.enabled && (reading.settings?.isOn($0) ?? false) },
                          status: reading.settings?.substack) { flipSubstack($0, on: $1) }
    }

    static func substackWays(isOn: (SubstackList) -> Bool, status: SubstackListsStatus?,
                             flip: @escaping (SubstackList, Bool) -> Void) -> [SourceWayIn] {
        SubstackList.allCases.map { list in
            let on = isOn(list)
            return SourceWayIn(id: "substack-\(list.id)", icon: .symbol("globe"), title: SubstackListWords.title(list),
                               control: .toggle(on) { flip(list, $0) },
                               help: SubstackListWords.detail(list, on: on, status: status) + " "
                                   + Copy.Reading.substackIntro)
        }
    }

    /// "Following N publications" — the area's one line, only when the person follows any.
    private var substackFollowing: String? {
        let following = SubstackFollowing.count(store.feeds.value ?? [])
        return following > 0 ? Copy.Reading.substackFollowing(following) : nil
    }

    // MARK: - The content

    /// A connector's channel, in either state: the backend sends `["connect"]` before it is connected and
    /// `["sync", "disconnect"]` after (`channel_registry._connector_channel`), so matching "connect" alone lost a
    /// connected account's Disconnect and a lapsed one's Reconnect (review of #593).
    nonisolated static func connectorChannel(in channels: [SourceChannel]) -> SourceChannel? {
        channels.first { $0.actions.contains("connect") || $0.actions.contains("disconnect") }
    }

    /// The This Mac sources' browser (accounts → collections → items), under the one thing each still chooses: a
    /// recorder's folders (each folder's Manage; its meetings are the browser's) and Reminders' lists.
    @ViewBuilder
    private var thisMacContent: some View {
        switch row.entry.id {
        case SourceCatalog.hexId, SourceCatalog.meetingFoldersId:
            if !mine.isEmpty {
                SourceSection(title: Copy.SourceLayout.folders) {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(mine) { FolderChannelRow(channel: $0, showsItems: false) }
                    }
                }
                .environment(\.sourceDetailHeadShown, true)
            }
        case RemindersReader.channel:
            if remindersReader?.isEnabled == true {
                RemindersRow(channel: mine.first, pickerOnly: true)
                    .environment(\.sourceDetailHeadShown, true)
            }
        default:
            EmptyView()
        }
        ThisMacSourceContent(entry: row.entry, channels: mine)
    }

    @ViewBuilder
    private var contentSlot: some View {
        switch row.entry.id {
        case _ where ThisMacSourceContent.handles(row.entry):
            thisMacContent
        case "folders":
            if !mine.isEmpty {
                SourceSection(title: Copy.SourceLayout.folders) {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(mine) { FolderChannelRow(channel: $0) }
                    }
                }
                .environment(\.sourceDetailHeadShown, true)
            }
            cameIn
        default:
            cameIn
            if row.entry.id == TabGroupWatcher.channel { TabGroupsOpenNow() }
        }
    }

    // MARK: - The footer

    @ViewBuilder
    private var footerSlot: some View {
        let entry = row.entry
        switch entry.id {
        case CalendarRow.channelId: CalendarSlot(slot: .footer)
        case ContactsReader.channel: ContactsSlot(slot: .footer)
        case RemindersReader.channel: RemindersSlot(slot: .footer)
        case AppleBooksReader.channel: AppleBooksSlot(slot: .footer, channel: mine.first)
        case MessagesWatcher.channel: ChatPickerSlot(slot: .footer, kind: .messages)
        case WhatsAppWatcher.channel: ChatPickerSlot(slot: .footer, kind: .whatsApp)
        case TelegramChats.channel: TelegramSlot(slot: .footer)
        case AppleNotesWatcher.channel: NotesSlot(slot: .footer)
        case LocalSourceWatcher.wisprChannel: WisprSlot(slot: .footer, notInstalled: row.notInstalled)
        case "folders": FolderSlot(slot: .footer, meetings: nil, hasFolders: !mine.isEmpty)
        case SourceCatalog.hexId: FolderSlot(slot: .footer, meetings: SourceCatalog.hexId, hasFolders: !mine.isEmpty)
        case SourceCatalog.meetingFoldersId: FolderSlot(slot: .footer, meetings: "", hasFolders: !mine.isEmpty)
        case "notion":
            if let api = channels.first(where: { $0.id == "notion-api" }) {
                ConnectorSlot(slot: .footer, channel: api, title: "Notion", needsSignIn: row.status == .needsSignIn)
            }
        default:
            if let connector = Self.connectorChannel(in: mine) {
                ConnectorSlot(slot: .footer, channel: connector, title: entry.title, needsSignIn: false)
            } else {
                SourcePageFooter(actions: plainFooter, note: feedNote)
            }
        }
    }

    /// The quiet actions of a source with no reader of its own: Refresh where something can be read again, a feed's
    /// Manage, and — on the pages they act on — browser reading and exploring saved sites.
    private var plainFooter: [SourceFooterAction] {
        var out: [SourceFooterAction] = []
        if let channel = mine.first(where: { $0.connected }), let tile = row.entry.tile,
           channel.actions.contains("manage") {
            out.append(SourceFooterAction(id: "manage", title: Copy.Catalog.manage) { flowTile = tile })
        }
        if let channel = mine.first(where: { $0.connected && $0.actions.contains("poll") && $0.count > 0 }) {
            out.append(.refresh { Task { feedNote = (try? await ChannelActions.poll(channel.id)) ?? nil } })
        } else if let channel = mine.first(where: { $0.connected && $0.actions.contains("sync") }) {
            out.append(.refresh { refresh(channel.id) })
        }
        let actions = SourcePageActions.of(row.entry, exploreGone: exploreCache.isGone)
        if actions.contains(.exploreSavedSites) {
            out.append(SourceFooterAction(id: "explore", title: Copy.Explore.button, help: Copy.Explore.buttonHelp) {
                showExploreSheet = true
            })
        }
        if actions.contains(.readingInBrowser) {
            out.append(SourceFooterAction(id: "reading", title: Copy.SourceLayout.browserSettings,
                                          help: Copy.SourceLayout.browserSettingsHelp) { showReadingSheet = true })
        }
        if row.entry.overviewId != nil {
            out.append(SourceFooterAction(id: "agents", title: Copy.Catalog.openAgents) { router.routeToAgents() })
        }
        return out
    }

    private func refresh(_ id: String) {
        Task {
            do {
                feedNote = try await ChannelActions.sync(id, store: store, watcher: watcher, local: localSources,
                                                         calendar: calendarReader, tabGroups: tabGroups,
                                                         contacts: contacts, messages: messagesWatcher,
                                                         watchHistory: watchHistory)
            } catch {
                feedNote = AddSourceSheet.friendlyError(error)
            }
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }

    private func verbTitle(_ verb: SourceCatalogVerb) -> String {
        switch verb {
        case .connect(let words): words
        case .turnOn: Copy.Catalog.turnOn
        case .importFile: Copy.Catalog.importFile
        case .openAgents: Copy.Catalog.openAgents
        }
    }

    private func flipSubstack(_ list: SubstackList, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet || !reading.enabled {
                consentSubstack = list
            } else {
                _ = await reading.setSubstackList(list, on)
            }
        }
    }

    private func flipYouTube(_ list: YouTubeList, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet || !reading.enabled {
                consentYouTube = list
            } else {
                _ = await reading.setYouTubeList(list, on)
            }
        }
    }

    private func flipSavedList(_ site: String, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet || !(reading.settings?.agentEnabled ?? false) {
                consentSavedList = true
                consentSite = site
            } else {
                _ = await reading.setSavedList(site, on)
            }
        }
    }

    /// Settings' rule (`ReadingWebView.flip`): turning a site on without a current acknowledgement raises the
    /// first-use sheet, and nothing changes until its "Turn on"; otherwise one call (`setSite`, never acknowledging).
    private func flip(_ site: String, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet {
                consentSavedList = false
                consentSite = site
            } else {
                _ = await reading.setSite(site, allowed: on)
            }
        }
    }

    // MARK: - What came in

    /// source-page-v3 — the one search, then what came in, in the source's own unit: a harness's conversations, else
    /// each list channel's rows (a chat, a watched day, a saved thing, a note…). Nothing at all — no search, no empty
    /// heading — for a source with no list yet (DR-81: an empty section is not drawn); its settings say how to start.
    @ViewBuilder
    private var cameIn: some View {
        if let overview, overview.kind == .harness {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SourceSearchHeader(query: $query, prompt: Copy.conversationsFind)
                HarnessConversationsView(source: overview, onSelectEntity: onSelectEntity, query: query,
                                         cap: SourceItemsRules.cap, onAll: { drill = .conversations })
            }
        } else if !listChannels.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SourceSearchHeader(query: $query, prompt: searchPrompt)
                ForEach(listChannels, id: \.id) { list in
                    // 2026-11-03 — a chat source's chats are the page: all of them, paged, never "All N" (the apps
                    // list every chat; a person keeps a few dozen, where a feed keeps thousands).
                    SourceItemsSection(channel: list.id, saved: savedStyle, query: query,
                                       cap: ChatSourcePage.isChatSource(list.id) ? nil : SourceItemsRules.cap,
                                       label: list.label) {
                        drill = $0
                    }
                }
            }
        }
    }

    /// A list opened in the page's place (DR-81): "‹ <source>" and Esc return.
    @ViewBuilder
    private func drilled(_ drill: SourceDrill) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SourceDrillHead(source: row.entry.title, title: drill.title) { self.drill = nil }
            switch drill {
            case .all(let channel):
                SourceSearchHeader(query: $query, prompt: searchPrompt)
                SourceItemsSection(channel: channel, saved: savedStyle, query: query, cap: nil) { self.drill = $0 }
            case .chat(let item):
                SourceChatConversations(item: item)
            case .day(let item):
                Text(WatchedDayText.day(item, today: ISODay.today()).help)
                    .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                SourceDayVideos(item: item)
            case .conversations:
                if let overview {
                    SourceSearchHeader(query: $query, prompt: Copy.conversationsFind)
                    HarnessConversationsView(source: overview, onSelectEntity: onSelectEntity, query: query)
                }
            }
        }
    }
}

/// A channel's actions, without the row Settings drew around them: the detail's head already says its state.
/// Connect / Manage open the connector's own panel; a sync or a poll is "Refresh" (never "Sync now" or "Poll now",
/// app-inventory §8).
struct ChannelActionsBar: View {
    let channel: SourceChannel
    var tile: AddSourceTile?
    /// The words on the button that opens the source's own flow ("Add a feed", "Manage").
    var flowTitle: String = Copy.Catalog.manage
    /// Opens the source's own flow (a feed's Subscribe field and list): the channel's `manage` action.
    var openFlow: (() -> Void)? = nil

    @Environment(Store.self) private var store
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(WatchHistoryWatcher.self) private var watchHistory: WatchHistoryWatcher?
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @Environment(ContactsReader.self) private var contacts: ContactsReader?
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var vendor: WalkthroughVendor = .claude
    @State private var showConnector = false
    @State private var busy = false
    @State private var feedback: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if channel.actions.contains("connect") {
                    NeutralButton(title: Copy.Catalog.connect, size: .compact) { showConnector = true }
                }
                if channel.actions.contains("sync") {
                    action { try await ChannelActions.sync(channel.id, store: store, watcher: watcher,
                                                           local: localSources, calendar: calendarReader,
                                                           tabGroups: tabGroups, contacts: contacts,
                                                           messages: messages, watchHistory: watchHistory) }
                } else if channel.actions.contains("poll"), channel.count > 0 {
                    // Nothing subscribed is nothing to poll: the flow's button below is the one thing to do.
                    action { try await ChannelActions.poll(channel.id) }
                }
                if channel.actions.contains("manage"), let openFlow {
                    NeutralButton(title: flowTitle, size: .compact) { openFlow() }
                }
                if channel.actions.contains("disconnect") {
                    NeutralButton(title: Copy.Catalog.manage, size: .compact) { showConnector = true }
                }
            }
            if let feedback {
                Text(feedback).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            } else if let error = channel.lastError, !error.isEmpty {
                // Why nothing is arriving, in the backend's words (a feed this backend does not fetch, a failed sync).
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .sheet(isPresented: $showConnector) {
            SettingsSheet(title: channel.label, onClose: { showConnector = false }) {
                ConnectorSetupPanel(connectorId: channel.id, vendors: tile?.vendors ?? [], vendor: $vendor)
            }
        }
    }

    private func action(_ work: @escaping () async throws -> String) -> some View {
        NeutralButton(title: Copy.Catalog.refresh, size: .compact, isDisabled: busy) {
            Task {
                busy = true
                defer { busy = false }
                do { feedback = try await work() } catch { feedback = AddSourceSheet.friendlyError(error) }
            }
        }
    }
}

/// Apple Notes' own control (2026-10-23): Connect reads every folder once (the one Automation prompt) and turns on
/// keeping up; once on, Refresh reads now and Disconnect stops it (what came in stays). The detail drew only a bare
/// Refresh before, on a source that never read again on its own.
struct NotesControls: View {
    @Environment(AppleNotesWatcher.self) private var notes
    @Environment(Store.self) private var store
    @State private var busy = false
    @State private var feedback: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(notes.enabled ? Copy.Catalog.notesOn : Copy.Catalog.notesOff)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: notes.enabled ? Copy.Catalog.refresh : Copy.Catalog.connectNotes, size: .compact,
                              isDisabled: busy) { read() }
                if notes.enabled {
                    NeutralButton(title: Copy.Catalog.disconnect, size: .compact) {
                        notes.disconnect()
                        feedback = nil
                    }
                }
            }
            if let line = feedback ?? failure {
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// An unattended read that failed (Automation turned off, a demo memory open), in the reader's own words.
    private var failure: String? {
        if case .failed(let why) = notes.status { return why }
        return nil
    }

    private func read() {
        Task {
            busy = true
            defer { busy = false }
            do {
                let r = try await notes.syncNow()
                feedback = "\(r.new) new · \(r.skipped) unchanged"
                await store.refresh([.channels, .status, .sources])
            } catch {
                feedback = AddSourceSheet.friendlyError(error)
            }
        }
    }
}
