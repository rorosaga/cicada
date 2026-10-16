import SwiftUI

/// G71 (owner 2026-10-16) — the YouTube videos watched in Chrome, nested under Chrome in Integrations → Browsers like
/// the tab groups: its own switch (off by default), "Live", what memory holds, "Last synced …" and an × while a read
/// runs. A refused read names its fix where it failed.
struct WatchHistoryRow: View {
    let channel: SourceChannel?
    let now: Date
    @Environment(WatchHistoryWatcher.self) private var watcher
    @Environment(SyncActivity.self) private var activity

    var body: some View {
        SourceRow(model: WatchHistoryRows.model(enabled: watcher.enabled, status: watcher.status, videos: watcher.videos,
                                                channel: channel, run: activity.run(for: WatchHistoryWatcher.channel)),
                  now: now, onCancel: { activity.cancel(WatchHistoryWatcher.channel) }) {
            Toggle(Copy.watchHistorySwitch, isOn: Binding(
                get: { watcher.enabled },
                set: { on in if on { Task { await watcher.enable() } } else { watcher.disable() } }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
        }
        .padding(.leading, CicadaTheme.scaled(SourceRow<EmptyView>.markSize))
        .settingsRow(.channel(WatchHistoryWatcher.channel))
    }
}

/// The row, pure (WatchHistoryWatcherTests).
enum WatchHistoryRows {
    static func model(enabled: Bool, status: WatchHistoryWatcher.Status, videos: Int?, channel: SourceChannel?,
                      run: SyncActivity.Run?) -> SourceRowModel {
        var model = SourceRowModel(id: WatchHistoryWatcher.channel, origin: "youtube-history", title: Copy.watchHistoryTitle)
        guard enabled else {
            model.line = Copy.watchHistoryOffLine
            return model
        }
        model.meta = Copy.tabGroupsLive
        switch status {
        case .missing: model.line = Copy.watchHistoryNoneYet
        case .failed: model.line = nil
        default: model.line = Copy.watchHistoryCount(videos ?? channel?.count ?? 0)
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
