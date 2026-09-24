import SwiftUI

/// Settings → Integrations (G126) — a categorized, logo-first page over the
/// existing `GET /sources/channels` / `GET /sources/overview` registry,
/// reusing `ChannelActions` (the same sync/poll implementation the Feed's
/// `ConnectedChannelsStrip` already calls) and `AddSourceTile` (the Feed's
/// own catalog) rather than adding a second sync path or a second catalog.
/// **No new adapter, no new backend field** — this page only reads and
/// routes into what already exists (G126's own scope note: "page only").
///
/// This is Task 2's stub fleshed out in place, not a second file.
struct IntegrationsView: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(LocalSourceWatcher.self) private var localSources
    /// Looked up once per appearance, not per body evaluation: it is a
    /// synchronous LaunchServices call on the main actor (task 7 review r1).
    /// Re-checked on every appearance so installing Obsidian while the app
    /// runs shows the row the next time the page opens.
    @State private var obsidianInstalled = false
    /// Round 4 (C9) — the browsers on this Mac, by bundle id; looked up on appearance like Obsidian (a Launch
    /// Services call per catalog row, never per body evaluation).
    @State private var browsers = BrowserInventory.empty

    /// One row per export-only social platform: no persisted backend
    /// channel exists for these (`AddSourceTile.channelIds` is `[]` for all
    /// four — the walkthrough sheet is the only way in today), so they can
    /// only ever appear here as a pointer into the Feed's `+` sheet, never
    /// as a connected/disconnected row like the thirteen real channels.
    static let exportOnlyTiles: [AddSourceTile] = [.instagram, .youtube, .linkedin, .tiktok]

    private var channels: [SourceChannel] { store.channels.value ?? [] }
    private var harnessRows: [SourceOverview] {
        IntegrationHarnessRows.rows(from: store.sourcesOverview.value ?? [])
    }

    /// recent-work #12 — this page is also onboarding STEP 3, so its worst
    /// case is a brand-new install on the step whose whole purpose is
    /// "connect one channel", staring at a `PageHeader` over blank space
    /// while the backend is still starting. Four states, not two: a fetch in
    /// flight, a fetch that failed and left nothing behind, a confirmed-empty
    /// roster, and rows. Pure and static so the precedence is unit-testable
    /// without standing up a view — the same shape
    /// `ConnectedChannelsStrip.loadState` already uses, widened to the two
    /// domains this page reads.
    enum LoadState: Equatable { case loading, failed(String), empty, loaded }

    /// A latched error never hides rows the app already has: last known good
    /// beats a blank page (the Store's own "view models never blank" rule),
    /// so a snapshot on EITHER domain wins over `error` and `isLoading`.
    ///
    /// Final review F2 — requiring both was the bug: `overview` feeds only
    /// the three informational harness rows (`IntegrationHarnessRows.rows`),
    /// so a `GET /sources/overview` that fails while `GET /sources/channels`
    /// succeeds must not blank the thirteen channel rows the Store is
    /// already holding. Either snapshot is evidence; `.empty` needs both
    /// present and both empty, so a failed domain can never be read as
    /// "confirmed nothing here".
    static func loadState(channels: [SourceChannel]?, overview: [SourceOverview]?,
                          isLoading: Bool, error: String?) -> LoadState {
        if !(channels ?? []).isEmpty || !(overview ?? []).isEmpty { return .loaded }
        if let channels, let overview, channels.isEmpty, overview.isEmpty { return .empty }
        if isLoading { return .loading }
        if let error { return .failed(error) }
        // No snapshot, not refreshing, no latched failure — the fetch simply
        // has not started yet. Treat like loading rather than guessing.
        return .loading
    }

    private var isLoading: Bool {
        (store.channels.isEmpty && store.channels.isRefreshing)
            || (store.sourcesOverview.isEmpty && store.sourcesOverview.isRefreshing)
    }

    private var loadError: String? { store.domainErrors[.channels] ?? store.domainErrors[.sourcesOverview] }

    var body: some View {
        SettingsScroll {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                SettingsDetailHeader(section: .integrations)

                switch Self.loadState(channels: store.channels.value, overview: store.sourcesOverview.value,
                                      isLoading: isLoading, error: loadError) {
                case .loading:
                    loadingPlaceholder
                case .failed(let message):
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(CicadaTheme.font(size: 12))
                            .foregroundStyle(CicadaTheme.danger)
                        Text(message)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                case .empty:
                    Text(Copy.integrationsEmpty)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                case .loaded:
                    ForEach(IntegrationCategory.allCases) { category in
                        let rows = channels.filter { IntegrationCategory.of(channelId: $0.id) == category }
                        let extraRows = extraRowCount(category, rows: rows)
                        // A section renders only when it has evidence (mirrors
                        // `SourceSections.group`'s own rule) — an empty category
                        // reads as a broken page, not a completeness signal.
                        if !rows.isEmpty || extraRows > 0 {
                            categorySection(category, rows: rows)
                        }
                    }
                }
            }
            .padding(CicadaTheme.spacingXL)
        }
        .background(CicadaTheme.background)
        .onAppear { obsidianInstalled = AddFolderRow.isObsidianInstalled() }
        .task { browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value }
    }

    /// Rows a category renders beyond its channels — the informational harness
    /// rows, the export-only platforms, the "Add a folder" rows (G133) and the
    /// Wispr Flow row once Wispr Flow is on this Mac (G134).
    private func extraRowCount(_ category: IntegrationCategory, rows: [SourceChannel]) -> Int {
        switch category {
        case .chatAndAgents: harnessRows.count
        case .socialAndSaved: Self.exportOnlyTiles.count
        case .notesAndFiles: 1
        // Round-4 D2 (R-FA13): "Calendar on this Mac" is always offered — Connect is how it starts.
        case .feedsAndCalendars: 1
        case .voiceAndMeetings: showsWispr(rows) ? 1 : 0
        // Round 4 (C9): an installed browser is offered before its first sync (R-SR15).
        case .browsers: BrowserRows.shown(inventory: browsers, channels: rows).count
        default: 0
        }
    }

    private func showsWispr(_ rows: [SourceChannel]) -> Bool {
        localSources.wisprInstalled || rows.contains { $0.id == LocalSourceWatcher.wisprChannel }
    }

    /// Three grey rows under a spinner rather than a bare spinner: the page's
    /// own shape, so the layout does not jump when the real categories land.
    private var loadingPlaceholder: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Checking your integrations…")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            VStack(spacing: 2) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .fill(CicadaTheme.surface)
                        .frame(height: CicadaTheme.scaled(44))
                }
            }
            .padding(CicadaTheme.spacingSM)
            .glassCard()
        }
    }

    @ViewBuilder
    private func categorySection(_ category: IntegrationCategory, rows: [SourceChannel]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if category == .browsers {
                // The F-02 header: the section's name, and the browsers Cicada can't sync named once (decision 2).
                HStack(spacing: CicadaTheme.spacingSM) {
                    SectionLabel(category.title)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    BrowsersUnsupportedNote(inventory: browsers)
                }
            } else {
                SectionLabel(category.title)
            }

            VStack(spacing: 2) {
                // Chat & agents also carries the informational harness rows
                // (Claude Code, Cursor, …) — the same `kind == .harness` rows
                // the Sources grid already shows, so "how does an agent
                // conversation get in" reads as one list instead of a
                // channel-only half.
                if category == .chatAndAgents {
                    ForEach(harnessRows) { row in
                        IntegrationHarnessRow(source: row)
                    }
                }
                if category == .browsers {
                    BrowsersSection(channels: rows, inventory: browsers)
                }
                ForEach(rows.filter { !BrowsersSection.owns($0.id) }) { channel in
                    if channel.id.hasPrefix("folder:") {
                        FolderChannelRow(channel: channel)
                    } else if channel.id != LocalSourceWatcher.wisprChannel,
                              channel.id != CalendarRow.channelId {
                        // Wispr Flow and the Calendar app each have a row the app owns (below).
                        IntegrationChannelRow(channel: channel)
                    }
                }
                if category == .notesAndFiles {
                    AddFolderRow.folder
                    if obsidianInstalled { AddFolderRow.obsidian }
                }
                if category == .feedsAndCalendars {
                    CalendarRow(channel: rows.first { $0.id == CalendarRow.channelId })
                }
                if category == .voiceAndMeetings, showsWispr(rows) {
                    WisprFlowRow(channel: rows.first { $0.id == LocalSourceWatcher.wisprChannel })
                }
                if category == .socialAndSaved {
                    ForEach(Self.exportOnlyTiles) { tile in
                        IntegrationExportOnlyRow(tile: tile) {
                            router.routeToFeedAddSource(tile)
                        }
                    }
                }
            }
            .padding(CicadaTheme.spacingSM)
            .glassCard()
        }
    }
}

/// One real, backend-tracked channel, drawn as a `SourceRow` (round 4): its
/// mark, its label, what came in, "Last synced …" on the right, and at most
/// one trailing action.
///
/// `@State` can only live on a `View`, so this is its own child view rather
/// than inline state inside `IntegrationsView`'s `ForEach` — neither
/// existing `ConnectorSetupPanel` call site (`AddSourceSheet`'s own
/// `@State`, `ConnectedChannelsStrip`'s full-sheet hand-off) hands the panel
/// a `vendor` binding from outside, so a per-row binding is new plumbing
/// (verified against `dev` @ `2312887` — see the plan's own file-map note).
private struct IntegrationChannelRow: View {
    let channel: SourceChannel
    @Environment(Store.self) private var store
    /// Track I T1: a Sync now here is consent for a watched browser, so it goes
    /// through the watcher. The `Settings{}` scene injects it for this reason.
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(LocalSourceWatcher.self) private var localSources
    /// Round 4 (R-SR17) — where a running sync says it is running and can be stopped.
    @Environment(SyncActivity.self) private var activity
    @State private var vendor: WalkthroughVendor = .claude
    @State private var showConnector = false
    @State private var busy = false
    @State private var feedback: String?

    private var tile: AddSourceTile? { AddSourceTile.forChannel(channel.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            // Round 4 (decision 3, R-SR12) — the one `SourceRow`: bare mark, what came in, "Last synced …" or
            // "Syncing now" with an × (DR-34 height, DR-52 mark, DR-58 relative words re-read every 30 s).
            TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                SourceRow(model: model, now: context.date, onCancel: { activity.cancel(channel.id) }) { trailingAction }
            }
            // R-HS16 — a sheet centred on the window, never a popover at the panel's edge.
            .sheet(isPresented: $showConnector) {
                SettingsSheet(title: channel.label, onClose: { showConnector = false }) {
                    ConnectorSetupPanel(connectorId: channel.id, vendors: tile?.vendors ?? [], vendor: $vendor)
                }
            }
            if let feedback {
                Text(feedback)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .settingsRow(.channel(channel.id))
    }

    private var model: SourceRowModel {
        SourceRowModel(id: channel.id, origin: ConnectedChannelRow.origin(forChannel: channel.id), title: channel.label,
                       line: channel.connected ? SourceRowText.countLine(channel) : Copy.sourceNotConnected,
                       status: SourceRowText.status(channel: channel, watch: watcher.state(for: channel.id),
                                                    run: activity.run(for: channel.id)))
    }

    /// Controls over `channel.actions`, in priority order below: "connect"
    /// is the only action `channel_registry` ever pairs with a bare,
    /// unconnected connector row (`_connector_channel`'s `["connect"]`
    /// branch), so it's checked first and opens the same
    /// `ConnectorSetupPanel` the Feed's catalog uses (in a `SettingsSheet`
    /// (R-HS16) attached to the row's `HStack` in `body`, so both this branch
    /// and the "disconnect" branch below can drive the one `showConnector`
    /// flag without duplicating the sheet modifier). Once connected, a
    /// connector's actions become `["sync", "disconnect"]`: a plain "Sync
    /// now" button plus a "Manage" button that reopens the same panel — the
    /// panel's own `status.connected` branch is what actually renders
    /// Disconnect (`ConnectorSetupPanel.swift`). Final review (finding 1):
    /// the panel was reachable only for a *bare* connector row via
    /// "connect"; a *connected* row fell through to the plain "sync" branch
    /// below and had no way back into the panel at all, making Disconnect
    /// unreachable from this page — contradicting this page's own row
    /// contract (Connect … Disconnect, CLAUDE.md §Integrations,
    /// plan Task 4.4's "'disconnect' → covered inside the same
    /// ConnectorSetupPanel popover, not a second button" — which presumed a
    /// way back into that popover would exist). "sync"/"poll" alone (a
    /// non-connector channel) still render as bare buttons, unchanged.
    @ViewBuilder
    private var trailingAction: some View {
        if channel.actions.contains("connect") {
            NeutralButton(title: "Connect", size: .compact) { showConnector = true }
        } else if channel.actions.contains("disconnect") {
            HStack(spacing: CicadaTheme.spacingSM) {
                if channel.actions.contains("sync") {
                    actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store, watcher: watcher, local: localSources, calendar: calendarReader) }
                }
                NeutralButton(title: "Manage", size: .compact) { showConnector = true }
            }
        } else if channel.actions.contains("sync") {
            actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store, watcher: watcher, local: localSources, calendar: calendarReader) }
        } else if channel.actions.contains("poll") {
            actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
        }
    }

    private func actionButton(_ title: String, _ work: @escaping () async throws -> String) -> some View {
        NeutralButton(title: title, size: .compact, isDisabled: busy) {
            Task {
                busy = true
                defer { busy = false }
                do {
                    feedback = try await work()
                } catch {
                    feedback = AddSourceSheet.friendlyError(error)
                }
            }
        }
    }
}

/// An informational row for a captured harness (Claude Code, Cursor, …) —
/// `SourceOverview` rows carrying `kind == .harness`. No action: a harness
/// isn't something you connect or disconnect from here, capture is the
/// Stop hook / MCP tool call itself (G105) — this row only answers "is this
/// one of the things Cicada listens to".
private struct IntegrationHarnessRow: View {
    let source: SourceOverview

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            // R-HS18, DR-52 — the harness's own mark, bare. The clip is Track L's rule, not
            // decoration: `hermes` is the one full-bleed plate (R-AG8 retired the two Claude
            // rasters), so every surface clips to its own curvature (`PlatformTile`'s 0.2 ratio); a
            // no-op for a mark whose corners are already transparent. No `.markHover()`: the row
            // opens nothing.
            if let origin = IntegrationHarnessRows.markOrigin(for: source) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(28))
                    .clipShape(CicadaTheme.shape(CicadaTheme.scaled(28) * 0.2))
            } else {
                Image(systemName: IntegrationHarnessRows.otherAgentsSymbol)
                    .font(CicadaTheme.font(size: 18))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(source.label)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Captured automatically — no setup needed")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.harness(source.harness ?? source.id))
    }
}

/// A platform with no persisted channel yet (Instagram, YouTube, LinkedIn,
/// TikTok) — the only route in is a one-shot export walkthrough in the
/// Feed's `+` sheet, so this row's one action hands off there via
/// `AppRouter` (R9) instead of pretending to be a standing connection.
private struct IntegrationExportOnlyRow: View {
    let tile: AddSourceTile
    let onImport: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if let logoName = tile.logoName {
                LogoImage.platformTile(name: logoName, size: CicadaTheme.scaled(28), systemFallback: tile.icon)
            } else {
                // DR-52 — no tinted tile behind a fallback symbol.
                Image(systemName: tile.icon)
                    .font(CicadaTheme.font(size: 18))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(tile.title)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Import only — no standing connection")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
            Button("Import in Feed →", action: onImport)
                .buttonStyle(.bordered)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.exportOnly(tile.id))
    }
}
