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
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(InboxViewModel.self) private var inboxVM
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

    /// G129 slice 2 — open `removal` items proposed against THIS channel.
    /// `store.visibleInbox`, not `store.inbox.value`, so an optimistic
    /// resolve here hides the card the instant it's clicked, same as the
    /// main Inbox page (`InboxViewModel.items`).
    private var removals: [InboxItem] {
        guard let id = source.channelId else { return [] }
        return InboxItem.openRemovals(in: store.visibleInbox, channelId: id)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                if let channel { stateCard(channel) }
                if !removals.isEmpty { deletionsSection }
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
            HStack(alignment: .top) {
                // A watched browser reports what its watch is doing (G129); a
                // channel with no watch keeps the plain connected/not line,
                // because a light nobody updates is worse than no light.
                if let watchState = watcher.state(for: channel.id) {
                    BrowserStatusLight(state: watchState, error: watcher.error(for: channel.id))
                } else {
                    Text(channel.connected ? "Connected" : "Not connected")
                        .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                Spacer()
                if channel.actions.contains("sync") {
                    actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store) }
                }
                if channel.actions.contains("poll") {
                    actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
                }
            }
            // R-S5 — the count no longer arrives pre-formatted inside
            // `detail`; one composer puts it back in the reader's locale.
            if let detail = ChannelDetailLine.text(channel) {
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

    /// One write path (`InboxViewModel.resolve` → `POST /inbox/{id}/resolve`),
    /// two views: the unified Inbox and this page render the identical
    /// `InboxCardView` for the identical open items.
    private var deletionsSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Removed from \(source.label)")  // count-lint:ok — a source name, not a count
                .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            VStack(spacing: CicadaTheme.spacingSM) {
                ForEach(removals) { item in
                    InboxCardView(item: item) { resolution in
                        await inboxVM.resolve(
                            id: item.id, action: resolution.action, answer: resolution.answer,
                            optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                            mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor
                        )
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingMD).glassCard()
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
                    Text("\(g.folder) · \(UsageFormat.count(g.count))")
                        .font(CicadaTheme.font(size: 11)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover).clipShape(Capsule())
                }
            }
        }
    }
}
