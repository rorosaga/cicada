import SwiftUI

/// A browser / social / feed / messaging / import source's list (G124): under the one header (`SourceDetailHead`, which
/// holds the channel's state and Sync/Poll now since Sources v4), the removals proposed against it, folder/device
/// counts when there are folders, and what came in — a saved source's saved things, Messages by chat, watch history by
/// day, every other source's items by name.
struct ChannelSourceView: View {
    let source: SourceOverview

    @Environment(Store.self) private var store
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(InboxViewModel.self) private var inboxVM
    @Environment(AppRouter.self) private var router

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
            // Review of #372 — lazy all the way down, so a long captured list realises (and asks marks for) only the
            // rows on screen.
            LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                // Sources v4 — the channel's state, last sync and Sync now live in the one header (`SourceDetailHead`).
                // The held answer's own Undo row keeps the section up after its last removal (R-DI16).
                if !removals.isEmpty || inboxVM.heldRemoval(channel: source.channelId) != nil { deletionsSection }
                if source.intent == .saved {
                    // Sources v3 (owner 2026-10-19) — the second click's answer: everything saved from here, newest
                    // first, each with the site's own mark, the day and why it was saved; paged by the server.
                    CapturedItemsList(channel: source.itemsListId, style: .saved)
                } else {
                    capturedContent
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
        }
    }

    @ViewBuilder
    private var capturedContent: some View {
        let groups = SourceItemsGrouping.folders(items)
        // Sources v4: never an empty "By folder" heading — a source with no folders (Messages) draws none.
        if SourceItemsGrouping.showsFolders(groups) {
            folderCounts(groups)
        }
        if source.id == TabGroupWatcher.channel {
            TabGroupsOpenNow()
            // G161 — the groups Cicada brought in (each a snapshot the Reader opens), under what is open now.
            if let id = source.channelId { CapturedItemsList(channel: id) }
        } else if source.isWatchHistory {
            // Review of #347 — the days watched, each opening in the Reader (one episode per day; never a save).
            CapturedItemsList(channel: source.itemsListId, style: .open)
        } else if items.isEmpty, let id = source.channelId {
            // G161 — a source whose items are not saved links (Notes, Calendar, a folder, Wispr Flow): what
            // came in, by name, is this page's content.
            CapturedItemsList(channel: id, style: .open)
        } else if items.isEmpty {
            Text("No saved items from this source yet.")
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        } else {
            // R-DL16 — a source's saved item opens in Sleep › Saved's detail column ("Open in Saved").
            let now = Date.now
            LazyVStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                ForEach(items) { item in
                    FeedListRow(item: item, style: .triage, selected: false, now: now) {
                        router.routeToSavedItem(item.mediaEntityId)
                    }
                }
            }
        }
    }

    private var deletionsSection: some View { ChannelRemovals(source: source) }

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
                        .font(CicadaTheme.captionFont).padding(.horizontal, CicadaTheme.spacingSM).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover).clipShape(Capsule())
                }
            }
        }
    }
}
