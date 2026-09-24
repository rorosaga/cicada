import SwiftUI

/// Round 4 (G160; F-02's sub-row) — Chrome's open tab groups, nested under Chrome in Integrations → Browsers: its own
/// switch (R-SR3), "Live", the groups as tags in Chrome's own colours (DR-44), "Last synced …" and an × while a read
/// runs (R-SR11).
struct TabGroupRow: View {
    let channel: SourceChannel?
    let now: Date
    @Environment(TabGroupWatcher.self) private var watcher
    @Environment(SyncActivity.self) private var activity

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SourceRow(model: TabGroupRows.model(enabled: watcher.enabled, status: watcher.status, groups: watcher.groups,
                                                channel: channel, run: activity.run(for: TabGroupWatcher.channel)),
                      now: now, onCancel: { activity.cancel(TabGroupWatcher.channel) }) {
                Toggle(Copy.tabGroupsSwitch, isOn: Binding(
                    get: { watcher.enabled },
                    set: { on in if on { Task { await watcher.enable() } } else { watcher.disable() } }))
                    .toggleStyle(.switch)
                    .controlSize(.mini)
                    .labelsHidden()
            }
            if watcher.enabled, !watcher.groups.isEmpty {
                FlowLayout(spacing: CicadaTheme.scaled(6)) {
                    ForEach(Array(watcher.groups.prefix(TabGroupRows.tagsShown).enumerated()), id: \.offset) { _, group in
                        Tag(text: group.title.isEmpty ? Copy.tabGroupUnnamed : group.title, dot: TabGroupColor.hue(group.color))
                    }
                }
                .padding(.leading, CicadaTheme.scaled(SourceRow<EmptyView>.markSize + 22))
            }
        }
        .padding(.leading, CicadaTheme.scaled(SourceRow<EmptyView>.markSize))
        .settingsRow(.channel(TabGroupWatcher.channel))
    }
}

/// The tab-group row, pure (TabGroupWatcherTests' neighbour).
enum TabGroupRows {
    static let tagsShown = 6

    static func model(enabled: Bool, status: TabGroupWatcher.Status, groups: [ChromiumTabGroup],
                      channel: SourceChannel?, run: SyncActivity.Run?) -> SourceRowModel {
        var model = SourceRowModel(id: TabGroupWatcher.channel, origin: "chrome-tab-group", title: Copy.tabGroupsTitle)
        guard enabled else {
            model.line = Copy.tabGroupsOffLine
            return model
        }
        model.meta = Copy.tabGroupsLive
        let tabs = groups.reduce(0) { $0 + $1.tabs.count }
        switch status {
        case .missing: model.line = Copy.tabGroupsNoneYet
        case .failed: model.line = nil
        default: model.line = groups.isEmpty ? Copy.tabGroupsNoneOpen : Copy.tabGroupsCount(groups.count, tabs: tabs)
        }
        if let run {
            model.status = .syncing(detail: run.detail, fraction: run.fraction, cancellable: run.cancellable)
        } else if case .failed(let why) = status {
            model.status = .problem(why)
        } else if let date = channel?.lastSyncDate {
            model.status = .synced(date)
        } else {
            model.status = status == .missing ? .idle : .notYet
        }
        return model
    }
}
