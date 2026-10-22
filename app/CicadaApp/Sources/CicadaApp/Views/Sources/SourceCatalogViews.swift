import SwiftUI

// G217 (ruling 36 D6) — the Sources page as the one catalogue: rows grouped by way in, each a logo tile, a name and a
// dot with one word (DR-34 row heights, DR-38 nothing said twice, DR-52 via the one tile adapter, DR-74 the detail's
// head). Settings → Integrations' rows and the "Add a source" grid both land here.

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
                SourceLogoTile(origin: row.entry.origin, size: style == .wide ? .row : .dense)
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
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var flowTile: AddSourceTile?
    @State private var browsers = BrowserInventory.empty

    private var channels: [SourceChannel] { store.channels.value ?? [] }
    private var mine: [SourceChannel] { SourceCatalog.channelsOf(row.entry, in: channels) }
    private var overview: SourceOverview? {
        SourceCatalog.overviewRow(for: row.entry, in: store.sourcesOverview.value ?? [])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            DetailHeader(title: row.entry.title, backLabel: hiddenListCount.map { Copy.Lists.sourcesBack($0) },
                         onShowList: onShowList, closeHelp: Copy.Lists.closeSource,
                         closeShortcut: KeyboardShortcut("[", modifiers: .command), onClose: onClose) {
                SourceLogoTile(origin: row.entry.origin)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            HStack(spacing: CicadaTheme.spacingMD) {
                StatusWord(word: row.status.word, tone: row.status.tone)
                if let line = SourceCatalog.line(row, now: .now) {
                    Text(line).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingMD)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                controls
                if let site = row.entry.site { readingToggle(site) }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingLG)
            .fixedSize(horizontal: false, vertical: true)
            cameIn
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), maxHeight: .infinity,
               alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
        .sheet(item: $flowTile) { tile in
            AddSourceSheet(initialTile: tile, onClose: { flowTile = nil }, flowOnly: true)
        }
        .task { await reading.loadSettings() }
        .sheet(isPresented: Binding(get: { consentSite != nil }, set: { if !$0 { consentSite = nil } })) {
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { consentSite = nil }) {
                ReadingFirstUseSheet(model: reading, site: consentSite, label: row.entry.title) { consentSite = nil }
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
        case MessagesWatcher.channel:
            MessagesRow(channel: mine.first)
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
                tileButton(Copy.Catalog.importFile)
            }
        case "chat-exports":
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(Copy.Catalog.chatExportsHere)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                NeutralButton(title: Copy.Catalog.openAgents, size: .compact) { router.routeToAgents() }
            }
        case "files":
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                IntakePanel(origin: .emptyState(.sources), compact: true)
                tileButton(Copy.Catalog.importFile)
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
                    Text(Copy.Catalog.instagramHonest)
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    tileButton(Copy.Catalog.importFile)
                }
            } else if !mine.isEmpty {
                ForEach(mine) { ChannelActionsBar(channel: $0, tile: entry.tile) }
            } else {
                tileButton(verbTitle(entry.verb))
            }
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

    /// Settings' rule (`ReadingWebView.flip`): turning a site on without a current acknowledgement raises the
    /// first-use sheet, and nothing changes until its "Turn on"; otherwise one call (`setSite`, never acknowledging).
    private func flip(_ site: String, on: Bool) {
        Task { @MainActor in
            await reading.loadSettings()
            if on, reading.needsFirstUseSheet {
                consentSite = site
            } else {
                _ = await reading.setSite(site, allowed: on)
            }
        }
    }

    // MARK: - What came in

    /// The source's own list as Sources v4 drew it (Messages by chat, watched days, a saved source's saves) when the
    /// overview has a row for it; else each connected channel's items. Calendar and Contacts list theirs in their row.
    @ViewBuilder
    private var cameIn: some View {
        let ownsList = [CalendarRow.channelId, ContactsReader.channel].contains(row.entry.id)
        if !ownsList, let overview {
            switch overview.kind {
            case .harness: HarnessConversationsView(source: overview, onSelectEntity: onSelectEntity)
            default: ChannelSourceView(source: overview)
            }
        } else if !ownsList, mine.contains(where: \.connected) {
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(mine.filter(\.connected)) { CapturedItemsList(channel: $0.id, style: .open) }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        } else {
            Spacer(minLength: 0)
        }
    }
}

/// A channel's actions, without the row Settings drew around them: the detail's head already says its state.
/// Connect / Manage open the connector's own panel; a sync or a poll is "Refresh" (never "Sync now" or "Poll now",
/// app-inventory §8).
struct ChannelActionsBar: View {
    let channel: SourceChannel
    var tile: AddSourceTile?

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
                } else if channel.actions.contains("poll") {
                    action { try await ChannelActions.poll(channel.id) }
                }
                if channel.actions.contains("disconnect") {
                    NeutralButton(title: Copy.Catalog.manage, size: .compact) { showConnector = true }
                }
            }
            if let feedback {
                Text(feedback).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
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
