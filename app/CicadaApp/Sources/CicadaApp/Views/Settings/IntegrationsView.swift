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
    /// Fired after a row hands off to the main window. The default is a no-op
    /// — in Settings → Integrations the window activation (`AppRouter`
    /// R7) IS the whole hand-off — but `FirstRunSheet` passes `finish`, so a
    /// hand-off from inside onboarding dismisses the sheet instead of routing
    /// to a Feed the person cannot see behind a modal (recent-work #8).
    var onHandOff: () -> Void = {}

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    /// One row per export-only social platform: no persisted backend
    /// channel exists for these (`AddSourceTile.channelIds` is `[]` for all
    /// four — the walkthrough sheet is the only way in today), so they can
    /// only ever appear here as a pointer into the Feed's `+` sheet, never
    /// as a connected/disconnected row like the thirteen real channels.
    private static let exportOnlyTiles: [AddSourceTile] = [.instagram, .youtube, .linkedin, .tiktok]

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
    /// so a snapshot on BOTH domains wins over `error` and `isLoading`.
    static func loadState(channels: [SourceChannel]?, overview: [SourceOverview]?,
                          isLoading: Bool, error: String?) -> LoadState {
        if let channels, let overview {
            return channels.isEmpty && overview.isEmpty ? .empty : .loaded
        }
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
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                PageHeader(title: Copy.integrations, subtitle: Copy.integrationsSubtitle) {}

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
                        let extraRows = category == .chatAndAgents ? harnessRows.count
                            : category == .socialAndSaved ? Self.exportOnlyTiles.count : 0
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
            Text(category.title.uppercased())
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

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
                ForEach(rows) { channel in
                    IntegrationChannelRow(channel: channel)
                }
                if category == .socialAndSaved {
                    ForEach(Self.exportOnlyTiles) { tile in
                        IntegrationExportOnlyRow(tile: tile) {
                            router.routeToFeedAddSource(tile)
                            onHandOff()
                        }
                    }
                }
            }
            .padding(CicadaTheme.spacingSM)
            .glassCard()
        }
    }
}

/// One real, backend-tracked channel: a 28pt mark, its label, the R8 state
/// line, and at most one trailing action.
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
    @State private var vendor: WalkthroughVendor = .claude
    @State private var showConnectorPopover = false
    @State private var busy = false
    @State private var feedback: String?

    private var tile: AddSourceTile? { AddSourceTile.forChannel(channel.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                mark
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.label)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(IntegrationRowState.line(channel))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(channel.lastError != nil ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                Spacer()
                trailingAction
            }
            .popover(isPresented: $showConnectorPopover, arrowEdge: .trailing) {
                ConnectorSetupPanel(connectorId: channel.id, vendors: tile?.vendors ?? [], vendor: $vendor)
                    .padding(CicadaTheme.spacingLG)
                    .frame(width: 320)
            }
            if let feedback {
                Text(feedback)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    @ViewBuilder
    private var mark: some View {
        if let logoName = ConnectedChannelRow.logoName(for: channel.id) {
            LogoImage.platformTile(name: logoName, size: 28, systemFallback: ConnectedChannelRow.icon(for: channel.id))
        } else {
            ZStack {
                Circle()
                    .fill(ConnectedChannelRow.tint(for: channel.id).opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                Image(systemName: ConnectedChannelRow.icon(for: channel.id))
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(ConnectedChannelRow.tint(for: channel.id))
            }
            .frame(width: 28, height: 28)
        }
    }

    /// Controls over `channel.actions`, in priority order below: "connect"
    /// is the only action `channel_registry` ever pairs with a bare,
    /// unconnected connector row (`_connector_channel`'s `["connect"]`
    /// branch), so it's checked first and opens the same
    /// `ConnectorSetupPanel` the Feed's catalog uses (in a `.popover`
    /// attached to the row's `HStack` in `body`, so both this branch and the
    /// "disconnect" branch below can drive the one `showConnectorPopover`
    /// flag without duplicating the popover modifier). Once connected, a
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
            Button("Connect") { showConnectorPopover = true }
                .buttonStyle(.bordered)
        } else if channel.actions.contains("disconnect") {
            HStack(spacing: CicadaTheme.spacingSM) {
                if channel.actions.contains("sync") {
                    actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store) }
                }
                Button("Manage") { showConnectorPopover = true }
                    .buttonStyle(.bordered)
            }
        } else if channel.actions.contains("sync") {
            actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store) }
        } else if channel.actions.contains("poll") {
            actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
        }
    }

    private func actionButton(_ title: String, _ work: @escaping () async throws -> String) -> some View {
        Button(title) {
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
        .buttonStyle(.bordered)
        .disabled(busy)
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
            ZStack {
                Circle()
                    .fill(CicadaTheme.accent.opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                Image(systemName: "bubble.left.and.bubble.right")
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
            }
            .frame(width: 28, height: 28)
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
                LogoImage.platformTile(name: logoName, size: 28, systemFallback: tile.icon)
            } else {
                ZStack {
                    Circle()
                        .fill(CicadaTheme.textSecondary.opacity(0.12))
                        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                    Image(systemName: tile.icon)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .frame(width: 28, height: 28)
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
    }
}
