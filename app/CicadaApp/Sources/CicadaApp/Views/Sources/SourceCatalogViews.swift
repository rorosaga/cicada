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
        return Set(settings.savedLists.filter { $0.value }.map { $0.key } + (youtube ? ["youtube"] : []))
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
        if let contacts { on[ContactsReader.channel] = contacts.enabled }
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

    private var channels: [SourceChannel] { store.channels.value ?? [] }

    // MARK: - source-page-v3: what the template reads

    /// The lists this page shows: the overview row's own list (Messages by chat, watched days, a saved source's saves,
    /// a harness's conversations), else each connected channel's.
    private var listChannels: [(id: String, label: String?)] {
        if let overview, overview.kind != .harness { return [(overview.itemsListId, nil)] }
        if overview != nil { return [] }
        let on = mine.filter(\.connected)
        return on.map { ($0.id, on.count > 1 ? $0.label : nil) }
    }

    private var savedStyle: Bool { overview?.intent == .saved }

    /// The status: the catalogue's word, the first channel's run (a read in progress, a failure, missing access) and
    /// the day the newest item came in.
    private var pageStatus: SourcePageStatus {
        let channel = mine.first
        let watch = channel.flatMap { watcher.state(for: $0.id) }
        let run = SourceRowText.status(channel: channel, watch: watch, run: channel.flatMap { activity?.run(for: $0.id) })
        return SourcePageStatus.of(row: row.status, run: run, latest: latest)
    }

    private var latest: String? {
        if let overview, overview.kind == .harness {
            return overview.lastActivityDate.map { ISODay.today(now: $0).description }
        }
        return listChannels.compactMap { itemsCache?.list($0.id)?.latest }.max()
    }

    /// Everything that used to be a paragraph on the page, one tap away (owner: "not so much text"): what the source is,
    /// what Cicada reads from it, where an export comes from, and the one honest limit.
    private var facts: [String] {
        let entry = row.entry
        var out: [String] = []
        if let overview { out.append(SourceBlurb.text(for: overview)) }
        else if let blurb = entry.channels.lazy.compactMap(SourceBlurb.text(id:)).first { out.append(blurb) }
        switch entry.id {
        case MessagesWatcher.channel: out.append(Copy.Messages.whatItReads)
        case WhatsAppWatcher.channel: out.append(Copy.Chats.whatsAppWhatItReads)
        case TelegramChats.channel: out.append(Copy.Chats.telegramWhatItReads)
        case "telegram": out.append(Copy.Catalog.telegramHonest)
        case "notion": out.append(Copy.Catalog.notionHow)
        default:
            if entry.verb == .turnOn, entry.overviewId == nil { out.append(Copy.Catalog.instagramHonest) }
        }
        if let how = SourceCatalog.exportHow(entry.id) { out.append(how) }
        if row.status == .waitingForAgent { out.append(Copy.Catalog.waitingForAgentHelp) }
        var seen = Set<String>()
        return out.filter { !$0.isEmpty && seen.insert($0).inserted }
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
        // source-page-v3 — the one template (`SourcePageViews.swift`): head, one status line, one search, what came
        // in, the source's settings last.
        VStack(alignment: .leading, spacing: 0) {
            DetailHeader(title: row.entry.title, backLabel: hiddenListCount.map { Copy.Lists.sourcesBack($0) },
                         onShowList: onShowList, closeHelp: Copy.Lists.closeSource,
                         closeShortcut: KeyboardShortcut("[", modifiers: .command), onClose: onClose) {
                SourceLogoTile(origin: row.entry.origin)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            SourceStatusLine(status: pageStatus, facts: facts, title: row.entry.title)
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingMD)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    if let drill {
                        drilled(drill)
                    } else {
                        if let overview, overview.kind != .harness, !removalsEmpty(overview) {
                            ChannelRemovals(source: overview)
                        }
                        cameIn
                        if row.entry.id == TabGroupWatcher.channel { TabGroupsOpenNow() }
                        SourcePageSettings {
                            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                importHow
                                controls
                                if let site = row.entry.site { readingToggle(site) }
                                if let site = row.entry.site, SourceCatalog.savedListSites.contains(site) {
                                    savedListToggle(site)
                                }
                            }
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), maxHeight: .infinity,
               alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
        .sheet(item: $flowTile) { tile in
            AddSourceSheet(initialTile: tile, onClose: { flowTile = nil }, flowOnly: true)
        }
        .task { await reading.loadSettings() }
        // G136 R-SU18 — a palette conversation row lands on its agent's page with the search filled.
        .onAppear { takeConversationQuery() }
        .onChange(of: router.pendingConversationQuery) { _, _ in takeConversationQuery() }
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

    // MARK: - The source's own control

    @ViewBuilder
    private var controls: some View {
        let entry = row.entry
        switch entry.id {
        case CalendarRow.channelId:
            CalendarRow(channel: mine.first)
        case ContactsReader.channel:
            ContactsRow(channel: mine.first)
        case RemindersReader.channel:
            RemindersRow(channel: mine.first)
        case MessagesWatcher.channel:
            MessagesRow(channel: mine.first)
        case WhatsAppWatcher.channel:
            WhatsAppSourceRow(channel: mine.first)
        case TelegramChats.channel:
            TelegramSourceRow(channel: mine.first)
        case SourceCatalog.tracesId:
            // Owner 2026-10-26 — once traces were ever on they have their own page; Sources keeps a link to it.
            if tracesPage { TracesSourcesLink() } else { TracesControls() }
        case LocalSourceWatcher.wisprChannel:
            WisprFlowRow(channel: mine.first)
        case "folders":
            VStack(alignment: .leading, spacing: 2) {
                ForEach(mine) { FolderChannelRow(channel: $0) }
                AddFolderRow.folder
            }
        case "youtube":
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                    WatchHistoryRow(channel: mine.first, now: context.date)
                }
                ForEach(YouTubeList.allCases) { youtubeListToggle($0) }
                tileButton(Copy.Catalog.importFile)
            }
        case AppleNotesWatcher.channel:
            NotesControls()
        case "telegram":
            // 2026-10-23: the detail drew the channel's actions — Telegram has none — so it showed nothing at all.
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                offLine(Copy.Catalog.telegramHonest)
                tileButton(Copy.Catalog.howToSetUp)
            }
        case "chat-exports":
            // CIC8 (2026-10-29) — the import itself, here: this row used to say "each chat export sits on its agent's
            // row" and send the person to Agents, whose *Import its chat export* sent them back to an empty Sources.
            // The one intake's panel (drop, *Choose a file…* opening in Downloads, each app's export page and steps).
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                IntakePanel(origin: .emptyState(.sources))
            }
        case "spotify":
            // G32: where the file comes from, then the one intake's drop — the "files" row's controls, no new pattern.
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                IntakePanel(origin: .emptyState(.sources), compact: true)
            }
        case "files":
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                IntakePanel(origin: .emptyState(.sources), compact: true)
                tileButton(Copy.Catalog.importFile)
            }
        case "readwise":
            // Ruling 47 tier 2: the connector panel the accounts already use (DR ids in the PR) — no new pattern.
            ConnectorSetupPanel(connectorId: "readwise", vendors: [], vendor: $vendor)
        case "notion":
            // G219 slice 1: the export's steps, then the one intake's drop (it reads the zip, previews it, imports).
            // Ruling 47 tier 2: the live connection first, in the same panel the accounts use.
            ConnectorSetupPanel(connectorId: "notion-api", vendors: [], vendor: $vendor)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                offLine(Copy.Catalog.notionHow)
                IntakePanel(origin: .emptyState(.sources), compact: true)
            }
        default:
            if entry.id.hasPrefix(SourceCatalog.browserPrefix) {
                BrowsersSection(channels: channels,
                                inventory: BrowserInventory(installed: browsers.installed.filter {
                                    SourceCatalog.browserPrefix + $0.id == entry.id
                                }))
            } else if entry.overviewId != nil {
                NeutralButton(title: Copy.Catalog.openAgents, size: .compact) { router.routeToAgents() }
            } else if entry.verb == .turnOn {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    offLine(Copy.Catalog.instagramHonest)
                    tileButton(Copy.Catalog.importFile)
                }
            } else if !mine.isEmpty {
                // A feed's "manage" opens its tile's flow (the Subscribe field and the list) — 2026-10-23: the bar
                // drew only Refresh, so RSS and Calendar feeds offered no way to add a feed at all.
                ForEach(mine) { channel in
                    ChannelActionsBar(channel: channel, tile: entry.tile,
                                      flowTitle: channel.count > 0 ? Copy.Catalog.manage : verbTitle(entry.verb),
                                      openFlow: entry.tile.map { tile in { flowTile = tile } })
                }
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    tileButton(verbTitle(entry.verb))
                }
            }
        }
    }

    /// 2026-10-26 (owner: "For TikTok there's an 'Import a file' option. Is this true?") — every source that imports a
    /// file says, before the button, exactly where the platform hands that file out (`SourceCatalog.exportHow`).
    /// source-page-v3: said in the settings only while the source is off (the first step); once on it lives behind
    /// "What Cicada reads" with the rest of the source's words.
    @ViewBuilder
    private var importHow: some View {
        if let how = SourceCatalog.exportHow(row.entry.id) { offLine(how) }
    }

    /// A source's how-to or honest limit, drawn in its settings only while it is off; always in its full words.
    @ViewBuilder
    private func offLine(_ text: String) -> some View {
        if row.status == .off {
            Text(text)
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
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

    @ViewBuilder
    private func tileButton(_ title: String) -> some View {
        if let tile = row.entry.tile {
            NeutralButton(title: title, size: .compact) { flowTile = tile }
        }
    }

    /// The per-site reading control (Reading the web left Settings, ruling 36 D6). The Turn on row's switch.
    private func readingToggle(_ site: String) -> some View {
        let on = reading.readableSites.contains(site)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Toggle(isOn: Binding(get: { on }, set: { value in flip(site, on: value) })) {
                Text(Copy.Catalog.readSite(row.entry.title))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            if let note = reading.note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// G206 (#426) — the saved list the person's own agent keeps current from their signed-in browser (app.md's spec,
    /// first slice, 2026-10-23: the switch and its off line). The backend refuses it while agent reading is off or
    /// unacknowledged, so the first-use sheet comes first then; a refusal's sentence shows under the reading switch.
    private func savedListToggle(_ site: String) -> some View {
        let on = reading.savedListsOn.contains(site)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Toggle(isOn: Binding(get: { on }, set: { value in flipSavedList(site, on: value) })) {
                Text(Copy.Catalog.readSavedList(site))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            if !on {
                Text(Copy.Catalog.savedListOff).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// 2026-10-26 — the YouTube lists the person's own agent keeps current (G71), on the YouTube row itself: on by
    /// default (onboarding asks once, pre-ticked; an existing install's are on when this memory holds YouTube), the
    /// same words as Reading in your browser's group, the first-use sheet first when agent reading is not yet on.
    private func youtubeListToggle(_ list: YouTubeList) -> some View {
        let on = reading.enabled && (reading.settings?.youtubeLists.isOn(list) ?? false)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Toggle(isOn: Binding(get: { on }, set: { value in flipYouTube(list, on: value) })) {
                Text(YouTubeListWords.title(list))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            Text(YouTubeListWords.detail(list, on: on, status: reading.settings?.youtube))
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
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
                    SourceItemsSection(channel: list.id, saved: savedStyle, query: query, label: list.label) {
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
