import AppKit
import SwiftUI

/// Round 4 (C9; decisions 2 and 3) — Settings → Integrations → Browsers: every browser on this Mac that Cicada can
/// really sync, with its own icon, what it reads and when it last synced. A browser Cicada cannot sync is named once
/// in the section's header (`BrowserInventory.unsupportedLine`), never as a row with a button.
struct BrowsersSection: View {
    let channels: [SourceChannel]
    let inventory: BrowserInventory

    /// The channels this section draws itself; the rest of the category (Safari's iCloud tabs) stays an ordinary
    /// channel row.
    static func owns(_ channelId: String) -> Bool { BrowserInventory.spec(forBookmarksChannel: channelId) != nil }

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(spacing: 2) {
                ForEach(BrowserRows.shown(inventory: inventory, channels: channels)) { spec in
                    BrowserSourceRow(spec: spec, channel: channels.first { $0.id == spec.bookmarksChannel },
                                     now: context.date)
                }
            }
        }
    }
}

/// The F-02 header's right half: the unsupported browsers' own marks, then one line ("Arc isn't supported yet").
/// Nothing when every browser here syncs.
struct BrowsersUnsupportedNote: View {
    let inventory: BrowserInventory

    var body: some View {
        if let line = BrowserInventory.unsupportedLine(inventory.unsupported) {
            HStack(spacing: CicadaTheme.spacingXS) {
                ForEach(inventory.unsupported) { spec in
                    BrowserMark(spec: spec, size: CicadaTheme.scaled(12))
                }
                Text(line)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .accessibilityElement(children: .combine)
        }
    }
}

private struct BrowserSourceRow: View {
    let spec: BrowserSpec
    let channel: SourceChannel?
    let now: Date
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(SyncActivity.self) private var activity
    @State private var busy = false
    @State private var feedback: String?

    private var channelId: String { spec.bookmarksChannel ?? spec.id }

    var body: some View {
        let watch = watcher.state(for: channelId)
        VStack(alignment: .leading, spacing: 2) {
            SourceRow(model: BrowserRows.model(spec, channel: channel, watch: watch, run: activity.run(for: channelId)),
                      now: now, onCancel: { activity.cancel(channelId) }) {
                action(BrowserRows.action(watch: watch))
            }
            // R-D6 kept: the Full Disk Access fix sits where the read failed (Safari).
            if watch == .blocked, let error = watcher.error(for: channelId) { FullDiskAccessHint(error: error) }
            if let feedback {
                Text(feedback).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .settingsRow(.channel(channelId))
    }

    @ViewBuilder
    private func action(_ action: BrowserRows.Action) -> some View {
        switch action {
        case .turnOn: NeutralButton(title: Copy.browserTurnOn, size: .compact, isDisabled: busy) { run() }
        case .syncNow: NeutralButton(title: Copy.browserSyncNow, size: .compact, isDisabled: busy) { run() }
        case .allow:
            NeutralButton(title: Copy.browserAllow, size: .compact) {
                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
            }
        case .none: EmptyView()
        }
    }

    /// Turn on and Sync now are one act (R-IA2): the consent, then one sync through the watch.
    private func run() {
        Task {
            busy = true
            defer { busy = false }
            do { feedback = try await watcher.syncNow(channelId) }
            catch let error where SyncCancellation.isCancellation(error) { feedback = Copy.syncStopped }
            catch { feedback = AddSourceSheet.friendlyError(error) }
        }
    }
}
