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
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(LocalSourceWatcher.self) private var localSources
    /// Round 4 (R-SR17) — the running sync and its ×.
    @Environment(SyncActivity.self) private var activity
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(AppRouter.self) private var router
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
                // The held answer's own Undo row keeps the section up after its last removal (R-DI16).
                if !removals.isEmpty || inboxVM.heldRemoval(channel: source.channelId) != nil { deletionsSection }
                let groups = SourceItemsGrouping.folders(items)
                if groups.count > 1 || (groups.first?.folder != SourceItemsGrouping.noFolder) {
                    folderCounts(groups)
                }
                if source.id == TabGroupWatcher.channel {
                    // G160 — the groups open right now, read on this Mac; never read back from the bank.
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        SectionLabel(Copy.tabGroupsTitle)
                        if let tabGroups, tabGroups.enabled {
                            ForEach(Array(tabGroups.groups.enumerated()), id: \.offset) { _, group in
                                HStack(spacing: CicadaTheme.spacingSM) {
                                    Tag(text: group.title.isEmpty ? Copy.tabGroupUnnamed : group.title,
                                        dot: TabGroupColor.hue(group.color))
                                    Text(Copy.tabsCount(group.tabs.count))
                                        .font(CicadaTheme.metaFont).monospacedDigit()
                                        .foregroundStyle(CicadaTheme.textSecondary)
                                }
                            }
                            if tabGroups.groups.isEmpty {
                                Text(Copy.tabGroupsNoneOpen)
                                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                            }
                        } else {
                            Text(Copy.tabGroupsOffLine)
                                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                } else if items.isEmpty {
                    Text("No saved items from this source yet.")
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                } else if source.id == "safari-bookmarks" {
                    // R-SR13 — Safari's own shape: Recently saved · Favorites · Other bookmarks, each item once (DR-38).
                    let now = Date.now
                    ForEach(SafariSections.groups(items), id: \.title) { group in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                            SectionLabel(group.title)
                            VStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                                ForEach(group.items) { item in
                                    FeedListRow(item: item, style: .triage, selected: false, now: now) {
                                        router.routeToFeedItem(item.mediaEntityId)
                                    }
                                }
                            }
                        }
                    }
                } else {
                    // R-DL16 — a source's saved item opens in the Feed's detail column ("Open in the Feed").
                    let now = Date.now
                    VStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                        ForEach(items) { item in
                            FeedListRow(item: item, style: .triage, selected: false, now: now) {
                                router.routeToFeedItem(item.mediaEntityId)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
        }
    }

    /// Round 4 (decision 3) — the channel's state as one `SourceRow`: what came in, "Last synced …" or "Syncing
    /// now" with an × (R-SR11/R-SR12); a failure is the row's `.problem`, so the old red line is gone.
    private func stateCard(_ channel: SourceChannel) -> some View {
        let watch = watcher.state(for: channel.id)
        let model = SourceRowModel(id: channel.id, origin: source.mark, title: SourceDisplayName.of(source),
                                   line: SourceRowText.countLine(channel) ?? ChannelDetailLine.text(channel),
                                   status: SourceRowText.status(channel: channel, watch: watch,
                                                                run: activity.run(for: channel.id)))
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                SourceRow(model: model, now: context.date, onCancel: { activity.cancel(channel.id) }) {
                    if channel.actions.contains("sync") {
                        actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store, watcher: watcher, local: localSources, calendar: calendarReader, tabGroups: tabGroups) }
                    }
                    if channel.actions.contains("poll") {
                        actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
                    }
                }
            }
            // R-D6 kept: the Full Disk Access fix is shown exactly where the read failed.
            if watch == .blocked, let error = watcher.error(for: channel.id) { FullDiskAccessHint(error: error) }
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
        NeutralButton(title: title, size: .compact, isDisabled: busy) {   // DR-40
            Task {
                busy = true
                do { feedback = ChannelFeedback(text: try await work(), isError: false) }
                catch { feedback = ChannelFeedback(text: AddSourceSheet.friendlyError(error), isError: true) }
                busy = false
                await store.refresh([.channels, .sources, .sourcesOverview, .status])
            }
        }
    }

    /// One write path (`InboxViewModel.answer` → the held `POST /inbox/{id}/resolve`, DR-42),
    /// two views: the unified Inbox and this page render the identical focus card and the
    /// identical Undo row (R-DI16).
    private var deletionsSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Removed from \(source.label)")  // count-lint:ok — a source name, not a count
                .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            VStack(spacing: CicadaTheme.spacingSM) {
                if let pending = inboxVM.heldRemoval(channel: source.channelId) {
                    InboxUndoRow(held: pending.held, item: pending.item, style: .wide, shortcutEnabled: true) {
                        inboxVM.undo(reopen: false)
                    }
                }
                ForEach(removals) { item in
                    InboxFocusCard(item: item, padding: CicadaTheme.spacingLG) { inboxVM.answer(item, $0) }
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
                    // R-SR13: Safari's internal keys in Safari's words ("Favorites/AI", not `BookmarksBar/AI`).
                    Text("\(SafariSections.displayFolder(g.folder)) · \(UsageFormat.count(g.count))")
                        .font(CicadaTheme.font(size: 11)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover).clipShape(Capsule())
                }
            }
        }
    }
}
