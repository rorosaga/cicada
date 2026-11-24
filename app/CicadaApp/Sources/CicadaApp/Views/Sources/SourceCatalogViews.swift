import SwiftUI

// G217 (ruling 36 D6) — the Sources page as the one catalogue: `SourcesRootList` at the root; beside an open source, rows
// in the grid's own sections, each a logo tile, a name and a dot with one word (DR-34 row heights, DR-38 nothing said
// twice, DR-52 via the one tile adapter, DR-74 the detail's head). The old Integrations page's rows and the "Add a
// source" grid both land here.

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

    /// ROR-138 (owner 2026-11-06: X, Instagram, LinkedIn, Reddit and Pinterest read Connected with no date) — the lists
    /// the agent has actually read, each with a date: turning a list on is a standing ask, not a connection.
    var savedListsRead: Set<String> {
        guard let settings else { return [] }
        var out = Set((settings.saved?.lists ?? [:]).filter { $0.value.lastReadAt != nil }.map { $0.key })
        if let yt = settings.youtube?.lists, yt.values.contains(where: { $0.lastReadAt != nil }) { out.insert("youtube") }
        if let ss = settings.substack?.lists, ss.values.contains(where: { $0.lastReadAt != nil }) {
            out.insert(SourceCatalog.substackId)
        }
        return out
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

    /// ROR-7 — the readers on this Mac that macOS stopped, by entry id, each with its reason: the page's *Needs you*. A
    /// reader the person never turned on is not waiting on them, so Contacts, Reminders and Apple Books count only while
    /// their switch is on; Calendar reaches `.denied` only from a Connect or a switch left on. Messages and WhatsApp
    /// carry no such switch, and `.needsAccess` does not mean never turned on: it can follow macOS refusing the person's
    /// own attempt, so it always waits on them.
    static func waitingOnAccess(calendar: CalendarReader?, contacts: ContactsReader?, reminders: RemindersReader?,
                                books: AppleBooksReader?, messages: MessagesWatcher?,
                                whatsApp: WhatsAppWatcher?, voiceMemos: VoiceMemosReader? = nil) -> [String: String] {
        var out: [String: String] = [:]
        if calendar?.status == .denied { out[CalendarRow.channelId] = Copy.sourceNeedsAccess }
        if let contacts, contacts.enabled, contacts.status == .denied {
            out[ContactsReader.channel] = Copy.sourceNeedsAccess
        }
        if let reminders, reminders.isEnabled, reminders.status == .denied {
            out[RemindersReader.channel] = Copy.sourceNeedsAccess
        }
        if let books, books.enabled, books.deniedByMac { out[AppleBooksReader.channel] = Copy.sourceNeedsAccess }
        if let voiceMemos, voiceMemos.enabled, voiceMemos.deniedByMac { out[VoiceMemosReader.channel] = Copy.sourceNeedsAccess }
        if case .needsAccess? = messages?.status { out[MessagesWatcher.channel] = Copy.sourceNeedsAccess }
        if case .needsAccess? = whatsApp?.status { out[WhatsAppWatcher.channel] = Copy.sourceNeedsAccess }
        return out
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
                // The name outranks the word: a long state word ("On · waits for your agent") truncated "Instagram" to
                // "Insta…" in the narrow list beside an open source (found in the real app).
                .layoutPriority(2)
                Spacer(minLength: CicadaTheme.spacingSM)
                // Its heading already says Connected; the word only cost the name its room.
                if (style == .wide || (style == .triage && !row.isConnectedHere)) && (row.status != .off || row.waitingOn != nil || row.notInstalled) {
                    // Whole or not at all: a word cut to a bare dot says nothing (the group's heading and the page do).
                    ViewThatFits(in: .horizontal) {
                        StatusWord(word: row.word, tone: row.tone).fixedSize()
                        Color.clear.frame(width: 0, height: 0)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: style == .titles || style == .hidden ? RowMetrics.titleOnly : RowMetrics.twoLine,
                        selected: selected)
        .accessibilityLabel("\(row.entry.title), \(row.word)")
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

/// The root's cards as narrow rows (DR-47, DR-34), for the list beside an open source: the same order as the root (what
/// needs the person, then what is connected, then what is not), so the keys walk what the root drew.
struct SourceCatalogList: View {
    let cards: [SourcesRoot.Card]
    let style: ColumnPlan.ListStyle
    var selection: SourcesSelection? = nil
    let open: (SourcesSelection) -> Void
    /// The clock the ages are read against; nil is the live one (a render pins it to its fixture).
    var clock: Date? = nil

    private var groups: [(title: String, cards: [SourcesRoot.Card])] {
        let titles: [SourcesRoot.Group: String] = [.needsYou: Copy.Catalog.needsYou, .connected: Copy.Catalog.connected,
                                                   .notConnected: Copy.Streams.notConnected]
        return [SourcesRoot.Group.needsYou, .connected, .notConnected].compactMap { group in
            let mine = cards.filter { $0.group == group }
            return mine.isEmpty ? nil : (titles[group] ?? "", mine)
        }
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                ForEach(Array(groups.enumerated()), id: \.offset) { index, group in
                    SectionLabel(group.title)
                        .padding(.horizontal, CicadaTheme.scaled(10))
                        .padding(.top, index == 0 ? 0 : CicadaTheme.scaled(14))
                        .padding(.bottom, CicadaTheme.scaled(4))
                    ForEach(group.cards) { card in
                        SourceCatalogRowView(row: card.row, style: style, selected: selection == .entry(card.id),
                                             now: clock ?? context.date) { open(.entry(card.id)) }
                            .id(SourcesSelection.entry(card.id))
                    }
                }
            }
        }
    }
}

/// One way in, opened (G245, ruling 78, plan 3.2): the head (tile, name, dot + word, and one quiet line of the account
/// and how it is read), the **Reads** block (a row per stream, a switch each, *Check now*), the source's own connect
/// step where a stream needs one, then what came in — item cards under tabs for the list kinds, the source's own content
/// for the rest — and a quiet footer. `compact` is onboarding's sheet: the head, Reads and the connect step, no items,
/// no Check now.
struct SourceCatalogDetail: View {
    let row: SourceCatalogRow
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void
    var onSelectEntity: ((String) -> Void)?
    /// The page's resolved streams (the backend's answer with this Mac's overlay on it). Nil: resolved here from the
    /// streams model alone, as onboarding's sheet does.
    var resolved: ResolvedStreams? = nil
    /// Onboarding's sheet: no items, no Check now (plan 3.2).
    var compact = false
    /// *Check now*: the page's check of this one source. Nil hides the button (no page owns a check here).
    var onCheckNow: (() -> Void)? = nil
    /// The stream the Items open on (nil is All), and the clock the ages are read against (nil is now): a hand-off or a
    /// render pins them.
    var startTab: String? = nil
    var clock: Date? = nil

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(ReadingAgentModel.self) private var reading
    @Environment(SourceStreamsModel.self) private var sourceStreams: SourceStreamsModel?
    @Environment(SourceStreamCheckModel.self) private var check: SourceStreamCheckModel?
    @Environment(AgentLiveProbe.self) private var agents: AgentLiveProbe?
    /// G245 — the first-use acknowledgement a switch asked for, by the contract's own words (`ReadingConsent`): one
    /// state for every list (a site's saved list, YouTube's, Substack's, a new one), mounted on this page.
    @State private var consent: ReadingConsent?
    /// A stream's switch flipped and not yet answered: drawn as flipped, rolled back when the write is refused.
    @State private var pendingSwitch: [String: Bool] = [:]
    /// Whether Accessibility is granted to this app (preflight only — ruling 77: the app never prompts for it).
    @State private var trusted = AXIsProcessTrusted()
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var flowTile: AddSourceTile?
    /// The connector panel's export walkthrough binding; a tier-2 connector has no export walkthrough.
    @State private var vendor: WalkthroughVendor = .claude
    @State private var browsers = BrowserInventory.empty
    /// G218 (owner 2026-10-26) — the Traces page is on the rail.
    @AppStorage(TracesPageVisibility.key) private var tracesPage = false
    /// source-page-v3 — the page's one search, and which of its lists fills the column instead of the page.
    @State private var query = ""
    /// The people tab chosen on a page that has a connections stream (nil is the page's own default).
    @State private var peopleTab: String?
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
    /// What the footer's last Refresh said.
    @State private var feedNote: String?
    /// A switch the backend refused, said under the Reads block until the next one.
    @State private var switchNote: String?

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
                                   notInstalled: row.notInstalled, waitingOn: row.waitingOn, browser: row.browser,
                                   readsThroughAI: SourceHeadLine.readsThroughAI(row.entry))
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
                             onShowList: onShowList, onClose: onClose, line: headLine, lineHelp: headHelp,
                             reads: AnyView(readsBlock))
        } else {
            page
        }
    }

    /// The standard source page (owner 2026-11-04; `SourcePageLayout`): head, Reads, connect step, content, footer.
    private var page: some View {
        SourcePageLayout(title: row.entry.title, origin: row.entry.origin, status: pageStatus, statusHelp: statusHelp,
                         line: headLine, lineHelp: headHelp,
                         backLabel: hiddenListCount.map { Copy.Lists.sourcesBack($0) }, onShowList: onShowList,
                         onClose: onClose) {
            if drill == nil {
                readsBlock
                connectSlot
                browserIdentity
            }
        } content: {
            if compact {
                EmptyView()
            } else if let drill {
                drilled(drill)
            } else {
                if let overview, overview.kind != .harness, !removalsEmpty(overview) {
                    ChannelRemovals(source: overview)
                }
                contentSlot
            }
        } footer: {
            if drill == nil && !compact { footerSlot }
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
        .task { await sourceStreams?.refresh() }
        // G136 R-SU18 — a palette conversation row lands on its agent's page with the search filled.
        .onAppear { takeConversationQuery() }
        .onChange(of: router.pendingConversationQuery) { _, _ in takeConversationQuery() }
        // The grant is given in System Settings and the person comes back: look again (a preflight, never a prompt).
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            trusted = AXIsProcessTrusted()
        }
        .sheet(item: $consent) { ask in
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consent = nil }) {
                ReadingFirstUseSheet(model: reading, site: nil, label: row.entry.title, consent: ask) {
                    consent = nil
                    Task {
                        await reading.load()
                        await sourceStreams?.refresh()
                    }
                }
            }
        }
        .task {
            if row.entry.id.hasPrefix(SourceCatalog.browserPrefix) {
                browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value
            }
        }
    }

    // MARK: - The head's line and the Reads block (G245)

    /// The page's streams: the answer the page resolved (or this build's own resolve of the streams model), each "Saves
    /// you make" row read fresh from this Mac, and — for a site with a save control the backend named no stream for — that
    /// row too, so the notch's switch always has its row here (plan 7: one truth).
    private var pageStreams: [ResolvedStream] {
        let base = (resolved ?? ownResolved).streams(row.id)
        var out = base.map { $0.stream.how == .click && $0.stream.owner == .app ? clickStream($0.stream) : $0 }
        if SiteSaveSite.named(row.id) != nil, !out.contains(where: { $0.stream.how == .click }) {
            out.append(clickStream(SourceStream(id: row.id + ".saves", label: Copy.Streams.savesYouMake, kind: .other("saves"),
                                                how: .click, owner: .app, control: .switch, state: .off)))
        }
        return out
    }

    /// The streams model alone, with no reader of this Mac's in it (onboarding's sheet; a render): what the backend says.
    private var ownResolved: ResolvedStreams {
        SourceStreamOverlay.resolve(sourceStreams?.value,
                                    app: StreamAppState(siteSavesOn: siteSavesOn, siteSavesOff: siteSavesOff,
                                                        permissions: [.accessibility: trusted]),
                                    entries: [row.entry])
    }

    /// This row's site, when this Mac notices its saves: what the person set, else on while the source is set up.
    private var siteSavesOn: Set<String> {
        SiteSavePrefs().noticing(row.id, status: row.status) ? [row.id] : []
    }
    private var siteSavesOff: Set<String> {
        SiteSavePrefs().explicit(row.id) == false ? [row.id] : []
    }

    private func clickStream(_ stream: SourceStream) -> ResolvedStream {
        SourceStreamOverlay.resolve(stream, of: row.id, entry: row.entry,
                                    app: StreamAppState(siteSavesOn: siteSavesOn, siteSavesOff: siteSavesOff,
                                                                           permissions: [.accessibility: trusted]),
                                    readerKeys: [], now: Date())
    }

    /// G245 — the source is read for free through the person's browser (a saved list, or a stream the backend says is read
    /// that way): its account, where it has one, is then a second way (`ConnectorSlot.hasFreeRoute`).
    private var hasFreeRoute: Bool {
        row.entry.savedListKey != nil || pageStreams.contains { $0.stream.how == .browser }
    }

    /// Whether the backend named this source's streams (else the page keeps today's controls).
    private var hasBackendStreams: Bool { !(resolved ?? ownResolved).streams(row.id).isEmpty }

    private var agentName: String? {
        SourceHeadLine.app(rows: Array(agents?.rows.values.map { $0 } ?? []))?.name
    }

    private var headLine: String? {
        SourceHeadLine.text(account: (resolved ?? ownResolved).accounts[row.id], streams: pageStreams, app: agentName)
    }

    private var headHelp: String? { SourceHeadLine.help(entryId: row.id, streams: pageStreams, app: agentName) }

    @ViewBuilder
    private var readsBlock: some View {
        let streams = pageStreams.filter { !$0.stream.isDerived }   // G246: "Saved another way" is no read, only a tab
        if !streams.isEmpty {
            TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                SourceReadsBlock(streams: streams, results: check?.results ?? [:], checking: check?.checking ?? [],
                                 pending: pendingSwitch, isChecking: check?.isChecking ?? false,
                                 checkedAt: check?.lastCheckedAt, failure: check?.failure,
                                 showsCheck: !compact && onCheckNow != nil, now: clock ?? context.date,
                                 onToggle: { toggle($0, on: $1) }, onFix: { NSWorkspace.shared.open($0.settingsURL()) },
                                 onCheck: { onCheckNow?() })
            }
            if let switchNote { SourceConnectLine(text: switchNote, isAttention: true) }
        }
    }

    /// A stream's switch (plan 3.2, section 7): the one connect plan decides — turn off is one call; turn on needs agent
    /// reading with a current acknowledgement, else the first-use sheet is raised here and nothing is written until its
    /// "Turn on". Optimistic: the row shows the flip at once and snaps back if the write is refused.
    private func toggle(_ resolved: ResolvedStream, on: Bool) {
        let stream = resolved.stream
        pendingSwitch[stream.id] = on
        Task { @MainActor in
            defer { pendingSwitch[stream.id] = nil }
            if stream.how == .click {
                SiteSavePrefs().setConnected(row.id, on)
                NotificationCenter.default.post(name: SiteSaveSwitches.changed, object: nil)
                trusted = AXIsProcessTrusted()
                return
            }
            guard let ref = stream.switchRef else { return }
            await reading.loadSettings()
            let state = SourceConnect.State(row: row, reading: reading, siteSavesOn: siteSavesOn, readersOn: [:],
                                            permissions: [:])
            let plan = SourceConnect.planSwitch(entry: row.id, setting: ref.setting, key: ref.key, on: on, state)
            let deps = SourceConnect.Deps(
                setList: { setting, key, on in await reading.setSwitch(setting: setting, key: key, on: on) },
                noticeSaves: { _ in }, startReader: { _ in false }, openPage: { _ in },
                raiseConsent: { consent = $0 }, lastNote: { reading.note })
            if case .failed(let note) = await SourceConnect.run(plan, entry: row.id, deps: deps) {
                switchNote = note ?? Copy.Streams.couldntSwitch
            } else {
                switchNote = nil
            }
            await reading.load()
            await sourceStreams?.refresh()
        }
    }

    // MARK: - The connect area

    /// ROR-114 — whose list a browser-read source is (handle, profile link), and Try again when it met a login wall:
    /// turning the list on again lifts the backend's pause.
    @ViewBuilder
    private var browserIdentity: some View {
        if let key = row.entry.savedListKey, let browser = row.browser {
            BrowserIdentityArea(site: row.entry.title, browser: browser) {
                Task { @MainActor in _ = await reading.setSavedList(key, true) }
            }
        }
    }

    /// The source's own connect step (a chat picker, a QR, a sign-in, a permission, a folder, a key, an address): shown
    /// where a stream needs one — a stream no switch can flip — a connected account, or no stream at all (the backend
    /// named none). A source whose every stream is a switch has none: its Reads rows are the whole of it.
    @ViewBuilder
    private var connectSlot: some View {
        if showsConnectStep { connectControls }
    }

    private var showsConnectStep: Bool {
        guard hasBackendStreams else { return true }
        if Self.connectorChannel(in: mine) != nil { return true }
        return pageStreams.contains { !$0.stream.isDerived && SourceStreamRow.control($0) == .setup }
    }

    @ViewBuilder
    private var connectControls: some View {
        let entry = row.entry
        switch entry.id {
        case CalendarRow.channelId:
            CalendarSlot(slot: .connect)
        case ContactsReader.channel: ContactsSlot(slot: .connect)
        case RemindersReader.channel: RemindersSlot(slot: .connect)
        case AppleBooksReader.channel: AppleBooksSlot(slot: .connect, channel: mine.first)
        case GoogleBooksKeyModel.id: GoogleBooksKeySlot(slot: .connect)
        case VoiceMemosReader.channel: VoiceMemosSlot(slot: .connect)
        case "goodreads": GoodreadsSlot(browserWay: hasBackendStreams ? nil : savedListWay("goodreads"))
        case "book-scan": BookAddSlot()
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
            // Nothing to connect: Spotify's list is a Reads row, Files and links only list what came in (the window's
            // drop, ⇧⌘I, the palette, Home and the Agents page are how a file arrives — no way row on this page).
            EmptyView()
        case "chat-exports":
            // A chat export is the chat vendors' own file: their marks are the right ones here. Each app's "request
            // your export" is a way in (its export page; its steps on hover); the file itself arrives by the window's
            // drop (ruling 58: exports are one-time).
            SourceConnectArea(ways: ChatVendor.allCases.map(ChatExportWay.of))
        case "notion":
            // Notion is its live connection (ruling 47 tier 2); no export way on its page.
            if let api = channels.first(where: { $0.id == "notion-api" }) {
                ConnectorSlot(slot: .connect, channel: api, title: "Notion", needsSignIn: row.status == .needsSignIn)
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
                ConnectorSlot(slot: .connect, channel: connector, title: entry.title,
                              ways: siteWays(withoutBrowser: webStart != nil), vendors: entry.tile?.vendors ?? [],
                              needsSignIn: row.status == .needsSignIn, primaryOverride: webStart,
                              hasFreeRoute: hasFreeRoute)
            } else if entry.site != nil || entry.savedListKey != nil {
                SourceConnectArea(primary: webStart, ways: siteWays(withoutBrowser: webStart != nil))
            } else if let feed = mine.first, feed.actions.contains("manage"), let tile = entry.tile {
                // A feed: the Subscribe field and the list are its flow.
                if feed.count == 0 {
                    SourceConnectArea(primary: SourcePrimaryAction(title: verbTitle(entry.verb)) { flowTile = tile },
                                      line: feed.lastError)
                } else if let error = feed.lastError, !error.isEmpty {
                    SourceConnectLine(text: error, isAttention: true)
                    // ROR-41: the gate is off and this Mac's background service is what turns it on.
                    if store.status.value?.gates?.feedFetch == false, !ServerConnection.current.isServer {
                        SettingsInlineLink(section: .general, row: .backgroundService, label: Copy.Catalog.feedsTurnOn)
                    }
                }
            } else if let tile = entry.tile, row.status == .off, entry.verb != .importFile {
                SourceConnectArea(primary: SourcePrimaryAction(title: verbTitle(entry.verb)) { flowTile = tile })
            }
        }
    }

    /// ROR-118 round 4 — a site read through the person's own AI app, still off, with no stream rows to turn on (the
    /// backend named none, so this is the old page's one button). With the streams answer the Reads rows are the way on.
    private var webStart: SourcePrimaryAction? {
        guard !hasBackendStreams, SourceHeadLine.readsThroughAI(row.entry), let key = row.entry.savedListKey,
              row.status == .off, !reading.savedListsOn.contains(key) else { return nil }
        return SourcePrimaryAction(title: Copy.SourceLayout.readSiteInBrowser(row.entry.title),
                                   help: Copy.Catalog.readSavedList(key)) { flipSavedList(key, on: true) }
    }

    private func siteWays(withoutBrowser: Bool) -> [SourceWayIn] {
        siteWays.filter { !(withoutBrowser && ($0.id == "saved" || $0.id == "browser")) }
    }

    /// An account's ways in beyond its connector: the browser reader's per-site switch and the saved list it keeps
    /// current — only while the backend names no streams (the Reads rows are those switches otherwise).
    private var siteWays: [SourceWayIn] {
        guard !hasBackendStreams else { return [] }
        var ways: [SourceWayIn] = []
        // ROR-114: a source with a saved list has ONE switch, "Read through your browser" (the list's). The site grant
        // beside it was refused (422) until Cicada had needed the browser for that site, so it could never be the way
        // on; it shows only while a grant is held, to take it away.
        if let site = row.entry.site, row.entry.savedListKey == nil || reading.readableSites.contains(site) {
            ways.append(.browser(on: reading.readableSites.contains(site)) { flip(site, on: $0) })
        }
        if let key = row.entry.savedListKey, let way = savedListWay(key) { ways.append(way) }
        return ways
    }

    /// The one *Read through your browser* switch of a saved list (ROR-114), also the first way in on Goodreads' page.
    private func savedListWay(_ key: String) -> SourceWayIn? {
        guard row.entry.savedListKey == key else { return nil }
        return SourceWayIn(id: "saved", icon: .symbol("globe"), title: Copy.SourceLayout.readInBrowser,
                           control: .toggle(reading.savedListsOn.contains(key)) { flipSavedList(key, on: $0) },
                           help: Copy.Catalog.readSavedList(key))
    }

    /// YouTube's ways in: the history Chrome keeps on this Mac and, while the backend names no streams, the two lists the
    /// person's agent keeps current.
    private var youtubeWays: [SourceWayIn] {
        var ways: [SourceWayIn] = []
        if let history = watchHistory {
            ways.append(SourceWayIn(id: "chrome", icon: .mark("chrome-bookmark"), title: Copy.SourceLayout.historyInChrome,
                                    control: .toggle(history.enabled) { on in
                                        if on { Task { await history.enable() } } else { history.disable() }
                                    },
                                    help: Copy.watchHistoryOffLine))
        }
        // With the streams answer the two lists are Reads rows; only what the Reads rows cannot flip stays a way.
        guard !hasBackendStreams else { return ways }
        for list in YouTubeList.allCases {
            let on = reading.enabled && (reading.settings?.youtubeLists.isOn(list) ?? false)
            ways.append(SourceWayIn(id: "list-\(list.id)", icon: .symbol("globe"), title: Copy.SourceLayout.youtubeList(list),
                                    control: .toggle(on) { flipYouTube(list, on: $0) },
                                    help: YouTubeListWords.detail(list, on: on, status: reading.settings?.youtube)))
        }
        return ways
    }

    /// G89 — Substack's three lists (Saved, History, Subscriptions), each the switch its own agent keeps current; the
    /// first-use sheet first while agent reading is not yet on (`flipSubstack`). What each reads is its hover; why it
    /// goes through the person's own agent (Substack offers readers no connection) is every switch's hover too.
    private var substackWays: [SourceWayIn] {
        guard !hasBackendStreams else { return [] }
        return Self.substackWays(isOn: { reading.enabled && (reading.settings?.isOn($0) ?? false) },
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
        let following = SubstackFollowing.count(channels)
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
        case "notion" where mine.contains(where: { $0.id == SourceBrowserTree.notionChannel }):
            ThisMacSourceContent(entry: row.entry, channels: mine)
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
            if let people = SourceStreamItems.connections(pageStreams) {
                peopleContent(people)
            } else {
                cameIn
            }
            if row.entry.id == TabGroupWatcher.channel { TabGroupsOpenNow() }
        }
    }

    /// LinkedIn: the saved posts and the connections are two tabs of one page; Connections is by date (plan 4).
    @ViewBuilder
    private func peopleContent(_ people: ResolvedStream) -> some View {
        let streams = pageStreams
        let selected = SourceStreamItems.peopleSelection(peopleTab ?? startTab, streams: streams)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            let tabs = SourceStreamItems.peopleTabs(streams)
            if tabs.count > 1 {
                TextTabs(tabs: tabs, selection: Binding(get: { selected }, set: { chosen in
                    Instant.run { peopleTab = chosen }
                }))
            }
            if selected == people.id {
                if people.stream.kind == .following {
                    FollowedAccountsSection(streamOn: people.stream.state == .on, kept: people.stream.count ?? 0)
                } else {
                    LinkedInConnectionsSection(streamOn: people.stream.state == .on, kept: people.stream.count ?? 0)
                }
            } else {
                cameIn
            }
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
        case GoogleBooksKeyModel.id: GoogleBooksKeySlot(slot: .footer)
        case VoiceMemosReader.channel: VoiceMemosSlot(slot: .footer)
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
                ConnectorSlot(slot: .footer, channel: connector, title: entry.title, needsSignIn: false,
                              hasFreeRoute: hasFreeRoute)
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
        // LinkedIn: the connections a past export left are kept for matching; forgetting them is a removal, not an import.
        // Shown only while something is kept (the connections stream's count is the kept directory's size).
        if row.entry.id == "linkedin", (SourceStreamItems.connections(pageStreams)?.stream.count ?? 0) > 0 {
            out.append(SourceFooterAction(id: "forget", title: LinkedInConnectionsWords.forget,
                                          confirm: (LinkedInConnectionsWords.forget, LinkedInConnectionsWords.forget,
                                                    Copy.Streams.forgetKeptHelp)) { forgetKeptConnections() })
        }
        // X: the accounts the person follows are kept the same way (ruling 79 (b)); forgetting them is a removal too.
        if row.entry.id == "x", let following = SourceStreamItems.connections(pageStreams), following.stream.kind == .following,
           (following.stream.count ?? 0) > 0 {
            out.append(SourceFooterAction(id: "forget-following", title: Copy.Streams.followingForget,
                                          confirm: (Copy.Streams.followingForget, Copy.Streams.followingForget,
                                                    Copy.Streams.followingForgetHelp)) { forgetFollowedAccounts() })
        }
        return out
    }

    private func forgetFollowedAccounts() {
        Task {
            do {
                feedNote = Copy.Streams.followingForgotten(try await APIClient.shared.forgetFollowedAccounts())
                await sourceStreams?.refresh()
            } catch {
                feedNote = AddSourceSheet.friendlyError(error)
            }
        }
    }

    private func forgetKeptConnections() {
        Task {
            do {
                feedNote = LinkedInConnectionsWords.forgotten(try await APIClient.shared.forgetLinkedInConnections())
                await sourceStreams?.refresh()
            } catch {
                feedNote = AddSourceSheet.friendlyError(error)
            }
        }
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

    /// A list's switch on the old ways (while the backend names no streams): off is one call; on needs agent reading with a
    /// current acknowledgement, else the first-use sheet is raised for that list by the contract's own words.
    private func flipList(_ setting: String, _ key: String, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet || !reading.enabled {
                consent = ReadingConsent(entryId: row.id, setting: setting, key: key)
            } else {
                _ = await reading.setSwitch(setting: setting, key: key, on: on)
                await sourceStreams?.refresh()
            }
        }
    }

    private func flipSubstack(_ list: SubstackList, on: Bool) { flipList("substackLists", list.rawValue, on: on) }
    private func flipYouTube(_ list: YouTubeList, on: Bool) { flipList("youtubeLists", list.rawValue, on: on) }
    private func flipSavedList(_ site: String, on: Bool) { flipList("savedLists", site, on: on) }

    /// The site's own grant, shown only while one is held, to take it away (ROR-114): never a way on.
    private func flip(_ site: String, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            _ = await reading.setSite(site, allowed: on)
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
        } else if row.entry.id == FeedChannelText.channel, !listChannels.isEmpty || (mine.first?.count ?? 0) > 0 {
            // ROR-108 — the feeds followed, each opening to what it brought in; a search reads across them.
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SourceSearchHeader(query: $query, prompt: searchPrompt)
                if SourceSearch.normalized(query).isEmpty {
                    FeedChannelsList(saved: savedStyle) { drill = $0 }
                } else {
                    SourceItemsSection(channel: FeedChannelText.channel, saved: savedStyle, query: query) { drill = $0 }
                }
            }
        } else if !listChannels.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SourceSearchHeader(query: $query, prompt: searchPrompt)
                if let cards = cardChannel {
                    // G245 — a list source's saves are cards under one tab per stream (plan 3.2 item 3).
                    SourceStreamItemsSection(channel: cards, streams: pageStreams, query: query, startTab: startTab,
                                             historyChannel: historyChannel, onAll: { drill = .all(channel: $0) },
                                             onDrill: { drill = $0 })
                }
                ForEach(listChannels.filter { $0.id != cardChannel && $0.id != historyChannel }, id: \.id) { list in
                    // 2026-11-03 — a chat source's chats are the page: all of them, paged, never "All N" (the apps
                    // list every chat; a person keeps a few dozen, where a feed keeps thousands).
                    if list.id == FeedChannelText.substackChannel, SourceSearch.normalized(query).isEmpty {
                        // G89 — the publications followed: a feed's items are never saves, whatever the page's others are.
                        FeedChannelsList(channel: list.id, label: list.label) { drill = $0 }
                    } else {
                        SourceItemsSection(channel: list.id, saved: savedStyle && list.id != FeedChannelText.substackChannel,
                                           query: query,
                                           cap: ChatSourcePage.isChatSource(list.id) ? nil : SourceItemsRules.cap,
                                           label: list.label) {
                            drill = $0
                        }
                    }
                }
            }
        }
    }

    /// The channel the watched history's days are listed under, once that history has its own tab (YouTube).
    private var historyChannel: String? {
        guard cardChannel != nil, SourceStreamItems.historyStream(pageStreams) != nil else { return nil }
        return overviewRows.first { $0.isWatchHistory }?.itemsListId
    }

    /// The channel whose items are cards: the saved list of a source with a tabbed list stream (plan 3.2 item 3).
    private var cardChannel: String? {
        guard SourceStreamItems.usesCards(pageStreams) else { return nil }
        return overviewRows.first { $0.intent == .saved }?.itemsListId ?? (savedStyle ? listChannels.first?.id : nil)
    }

    /// A list opened in the page's place (DR-81): "‹ <source>" and Esc return.
    @ViewBuilder
    private func drilled(_ drill: SourceDrill) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SourceDrillHead(source: row.entry.title, title: drill.title) { self.drill = nil }
            switch drill {
            case .all(let channel):
                SourceSearchHeader(query: $query, prompt: searchPrompt)
                if SourceListKey.streamParts(channel) != nil {
                    SourceStreamCards(key: channel, query: query, cap: nil) { _ in }
                } else {
                    SourceItemsSection(channel: channel, saved: savedStyle, query: query, cap: nil) { self.drill = $0 }
                }
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
