import SwiftUI

/// G129 slice 2 — the removals proposed against a channel, on its source page. One write path (`InboxViewModel.answer`
/// → the held `POST /inbox/{id}/resolve`, DR-42), two views: the unified Inbox and the source page render the
/// identical focus card and the identical Undo row (R-DI16). `store.visibleInbox`, so an optimistic resolve hides the
/// card the instant it is clicked.
struct ChannelRemovals: View {
    let source: SourceOverview

    @Environment(Store.self) private var store
    @Environment(InboxViewModel.self) private var inboxVM

    private var removals: [InboxItem] {
        guard let id = source.channelId else { return [] }
        return InboxItem.openRemovals(in: store.visibleInbox, channelId: id)
    }

    var body: some View {
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
}

/// G160 — the tab groups open right now, read on this Mac; never read back from the bank.
struct TabGroupsOpenNow: View {
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?

    var body: some View {
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
    }
}
