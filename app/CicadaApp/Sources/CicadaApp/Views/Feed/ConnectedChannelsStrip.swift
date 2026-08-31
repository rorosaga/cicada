import SwiftUI

/// The connected-capture-channels strip, lifted off the retired Capture page
/// (G62 → G68 §1). It sits above the Feed list because it answers the Feed's
/// own question — "where did all this come from, and what else could?" —
/// and collapses to a single line so it never competes with the list.
///
/// Every value is a projection over `Store.channels` (§5.5): correct on a
/// cold, offline launch, and this view starts no fetches.
struct ConnectedChannelsStrip: View {
    /// Opens the add-source sheet, optionally focused on one tile ("Manage…").
    let onManage: (AddSourceTile?) -> Void

    @Environment(Store.self) private var store
    @AppStorage("cicada.feedChannelsCollapsed") private var isCollapsed = false
    /// PR #19 round-4 review: keyed by channel id — two rows acting
    /// concurrently used to share a single `busyChannel: String?` /
    /// `feedback: ChannelFeedback?`, so whichever action finished last could
    /// clear the other row's still-in-flight spinner or replace its
    /// still-fresh result. A write for one channel id can never touch
    /// another's slot, regardless of which action started or finished first.
    @State private var busyChannels: Set<String> = []
    @State private var feedback: [String: ChannelFeedback] = [:]

    private var channels: [SourceChannel] { store.channels.value ?? [] }
    private var connected: [SourceChannel] { SourceChannel.sortedConnected(channels) }
    private var isLoading: Bool { store.channels.isEmpty && store.channels.isRefreshing }

    /// The count is the point of a collapsible strip, so it survives collapsing.
    static func stripTitle(connected: Int) -> String {
        connected == 0 ? "CONNECTED" : "CONNECTED (\(connected))"
    }

    /// PR #19 review: `store.channels` missing is not one state, it's two — a
    /// fetch still in flight (`.loading`) vs. one that already failed and left
    /// nothing behind (`.failed`) — and neither is "a confirmed empty roster"
    /// (`.loaded(connected: [])`, the only case "Nothing connected yet" may
    /// render for). Pulled out as a pure function so the precedence is
    /// unit-testable without a view.
    enum LoadState: Equatable {
        case loading
        case failed(String)
        case loaded(connected: [SourceChannel])
    }

    static func loadState(channels: [SourceChannel]?, isLoading: Bool, error: String?) -> LoadState {
        if let channels { return .loaded(connected: SourceChannel.sortedConnected(channels)) }
        if isLoading { return .loading }
        if let error { return .failed(error) }
        // No snapshot, not refreshing, no latched failure yet — the fetch
        // simply hasn't started. Treat like loading rather than guessing.
        return .loading
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) { isCollapsed.toggle() }
            } label: {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .rotationEffect(.degrees(isCollapsed ? 0 : 90))
                    Text(Self.stripTitle(connected: connected.count))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .tracking(1.2)
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isCollapsed
                                ? "Show connected sources, \(connected.count) connected"
                                : "Hide connected sources, \(connected.count) connected")

            if !isCollapsed {
                switch Self.loadState(channels: store.channels.value, isLoading: isLoading, error: store.domainErrors[.channels]) {
                case .loading:
                    HStack(spacing: CicadaTheme.spacingSM) {
                        ProgressView().controlSize(.small)
                        Text("Checking your sources…")
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                case .failed(let message):
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 12))
                            .foregroundStyle(CicadaTheme.danger)
                        Text(message)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                case .loaded(let connected) where connected.isEmpty:
                    Button { onManage(nil) } label: {
                        Text("Nothing connected yet — add a chat export, bookmarks, a feed or a calendar.")
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Copy.addASource)
                case .loaded(let connected):
                    VStack(spacing: 2) {
                        ForEach(connected) { channel in
                            ConnectedChannelRow(
                                channel: channel,
                                isBusy: busyChannels.contains(channel.id),
                                feedback: Binding(
                                    get: { feedback[channel.id] },
                                    set: { feedback[channel.id] = $0 }
                                )
                            ) { action in
                                handle(action, for: channel)
                            }
                        }
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    // MARK: - Actions (moved verbatim from SourcesView)

    private func handle(_ action: String, for channel: SourceChannel) {
        // Only this channel's own slot — a fresh action on one row must not
        // blank another row's still-showing result.
        feedback[channel.id] = nil
        switch action {
        case "poll": Task { await run(channel) { try await Self.poll(channel) } }
        case "sync": Task { await run(channel) { try await Self.sync(channel) } }
        default: onManage(AddSourceTile.forChannel(channel.id))
        }
    }

    private func run(_ channel: SourceChannel, _ work: @escaping () async throws -> String) async {
        busyChannels.insert(channel.id)
        do {
            feedback[channel.id] = ChannelFeedback(text: try await work(), isError: false)
        } catch {
            feedback[channel.id] = ChannelFeedback(text: AddSourceSheet.friendlyError(error), isError: true)
        }
        busyChannels.remove(channel.id)
        await store.refresh([.channels, .status, .sources, .feeds, .calendars])
    }

    private static let fetchDisabledHint =
        "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart."

    private static func poll(_ channel: SourceChannel) async throws -> String {
        if channel.id == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? Self.fetchDisabledHint : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? Self.fetchDisabledHint : "\(r.new) new item(s)"
    }

    private static func sync(_ channel: SourceChannel) async throws -> String {
        if channel.id == "notes" {
            let r = try await APIClient.shared.syncNotes()
            return "\(r.new) new · \(r.skipped) unchanged"
        }
        let r = try await APIClient.shared.syncBookmarks()
        return "\(r.new) new · \(r.skipped) already saved"
    }
}
