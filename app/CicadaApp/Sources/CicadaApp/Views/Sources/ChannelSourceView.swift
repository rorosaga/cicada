import SwiftUI

/// A browser / social / feed / messaging / import source's page (G124): its
/// channel state (joined from the `channels` snapshot by `channelId`),
/// Sync/Poll now where the channel supports it (the same actions the Feed's
/// connected-channel rows run — browser files are read HERE and posted as
/// bytes, R1 of the Safari import: the launchd backend has no Full Disk
/// Access and never opens `~/Library` itself), folder/device counts, and the
/// Feed's items filtered to this source's origins (R6 — a client-side filter
/// over the existing `sources` Store domain, no new endpoint).
struct ChannelSourceView: View {
    let source: SourceOverview

    @Environment(Store.self) private var store
    @State private var busy = false
    @State private var feedback: ChannelFeedback?

    private var channel: SourceChannel? {
        guard let id = source.channelId else { return nil }
        return (store.channels.value ?? []).first { $0.id == id }
    }

    /// The Feed's items that belong to this source — the rule itself lives on
    /// `SourceOverview` so it can be tested without a view.
    private var items: [MediaFeedItem] {
        source.ownedItems(from: store.sources.value ?? [])
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                if let channel { stateCard(channel) }
                let groups = SourceItemsGrouping.folders(items)
                if groups.count > 1 || (groups.first?.folder != SourceItemsGrouping.noFolder) {
                    folderCounts(groups)
                }
                if items.isEmpty {
                    Text("No saved items from this source yet.")
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                } else {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(items) { FeedRow(item: $0, showRelevance: false) }
                    }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
        }
    }

    private func stateCard(_ channel: SourceChannel) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack {
                Text(channel.connected ? "Connected" : "Not connected")
                    .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                if channel.actions.contains("sync") {
                    actionButton("Sync now") { try await BrowserImportActions.syncChannel(channel.id, store: store) }
                }
                if channel.actions.contains("poll") {
                    actionButton("Poll now") { try await pollNow(channel) }
                }
            }
            if let detail = channel.detail {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let error = channel.lastError, !error.isEmpty {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            if let feedback {
                Text(feedback.text).font(CicadaTheme.captionFont)
                    .foregroundStyle(feedback.isError ? CicadaTheme.danger : CicadaTheme.success)
                    .task(id: feedback) {
                        try? await Task.sleep(for: .seconds(5))
                        if !Task.isCancelled { self.feedback = nil }
                    }
            }
        }
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    /// Every action refreshes the overview alongside the channel/items
    /// domains: the card's counts and `connected` dot come from
    /// `/sources/overview`, not from `/sources/channels`.
    private func actionButton(_ title: String, _ work: @escaping () async throws -> String) -> some View {
        Button(title) {
            Task {
                busy = true
                do { feedback = ChannelFeedback(text: try await work(), isError: false) }
                catch { feedback = ChannelFeedback(text: AddSourceSheet.friendlyError(error), isError: true) }
                busy = false
                await store.refresh([.channels, .sources, .sourcesOverview, .status])
            }
        }
        .buttonStyle(.bordered).controlSize(.small).disabled(busy)
    }

    /// A user-initiated poll still honours the backend's fetch gate: the
    /// result says so plainly instead of reporting "0 new" as if it had run.
    private func pollNow(_ channel: SourceChannel) async throws -> String {
        let disabled = "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart."
        if channel.id == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new item(s)"
    }

    /// iCloud tabs group by device (the importer writes the device name into
    /// `folder:`); every other importer's `folder:` is a folder, board or
    /// section.
    private func folderCounts(_ groups: [(folder: String, count: Int)]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(source.kind == .browser && source.id == "safari-tabs" ? "By device" : "By folder")
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            FlowLayout(spacing: 6) {
                ForEach(groups, id: \.folder) { g in
                    Text("\(g.folder) · \(g.count)")
                        .font(.system(size: 11)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover).clipShape(Capsule())
                }
            }
        }
    }
}
