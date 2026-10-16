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
    /// Also claims Chrome's tab-group channel (G160), so the generic loop in `IntegrationsView` never draws it a
    /// second time; its sub-row sits under Chrome's own.
    static func owns(_ channelId: String) -> Bool {
        BrowserInventory.spec(forBookmarksChannel: channelId) != nil || channelId == TabGroupWatcher.channel
            || channelId == WatchHistoryWatcher.channel
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(spacing: 2) {
                ForEach(BrowserRows.shown(inventory: inventory, channels: channels)) { spec in
                    BrowserSourceRow(spec: spec, channel: channels.first { $0.id == spec.bookmarksChannel },
                                     now: context.date)
                    if spec.tabGroupsChannel != nil {
                        TabGroupRow(channel: channels.first { $0.id == TabGroupWatcher.channel }, now: context.date)
                    }
                    // G71 (2026-10-16): the YouTube videos watched in Chrome — its own switch, under Chrome.
                    if spec.id == WatchHistoryWatcher.browser {
                        WatchHistoryRow(channel: channels.first { $0.id == WatchHistoryWatcher.channel },
                                        now: context.date)
                    }
                }
                // G191 — next to where the bookmark watch is turned on: the question it may ask.
                SaveWhySwitchRow(inventory: inventory)
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
                action(BrowserRows.action(watch: watch, engine: spec.engine))
            }
            // R-D6 kept: the Full Disk Access fix sits where the read failed (Safari).
            if watch == .blocked, let error = watcher.error(for: channelId) { FullDiskAccessHint(error: error) }
            if let feedback {
                Text(feedback).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            // G161 — the bookmarks the last sync saw, by name.
            if channel?.connected == true {
                CapturedItemsList(channel: channelId)
                    .padding(.leading, CicadaTheme.scaled(SourceRow<EmptyView>.markSize + 22))
            }
        }
        .settingsRow(.channel(channelId))
    }

    @ViewBuilder
    private func action(_ action: BrowserRows.Action) -> some View {
        switch action {
        case .turnOn: NeutralButton(title: Copy.browserTurnOn, size: .compact, isDisabled: busy) { run() }
        case .syncNow: NeutralButton(title: Copy.browserSyncNow, size: .compact, isDisabled: busy) { run() }
        case .tryAgain: NeutralButton(title: Copy.browserTryAgain, size: .compact, isDisabled: busy) { run() }
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
            // A refused read already shows its fix under the row (FullDiskAccessHint); saying it twice helps no one.
            catch BrowserFileError.notReadable { feedback = nil }
            catch { feedback = AddSourceSheet.friendlyError(error) }
        }
    }
}

/// G191 — Settings → Integrations → Browsers: "Ask why when I bookmark something". Off by default (G191 (7)); per Mac,
/// beside the bookmark watch's own consent flags (`SaveWhyPrefs`). v2 (2026-10-14): one switch that works — turning
/// it on turns on the bookmark watch of every browser here (`SaveWhySetup`), named before the flip; once on, the row
/// says what is watched, names a missing permission with its one click, and says the next bookmark is the first asked.
/// Muted sites can be asked about again here.
struct SaveWhySwitchRow: View {
    let inventory: BrowserInventory
    @AppStorage(SaveWhyPrefs.enabledKey) private var enabled = false
    @Environment(BrowserWatcher.self) private var watcher
    @State private var muted = 0

    private var prefs: SaveWhyPrefs { SaveWhyPrefs(defaults: .standard) }

    private var isOn: Binding<Bool> {
        Binding(get: { enabled }, set: { on in
            if on { SaveWhySetup.turnOn(prefs: prefs, inventory: inventory, watcher: watcher) }
            else { prefs.enabled = false }
        })
    }

    private var status: SaveWhySetup.Status {
        SaveWhySetup.status(inventory: inventory, state: watcher.state(for:), isEnabled: watcher.isEnabled)
    }

    var body: some View {
        SettingsRow(.saveWhy, title: Copy.SaveWhy.switchTitle, detail: Copy.SaveWhy.switchDetail) {
            Toggle(Copy.SaveWhy.switchTitle, isOn: isOn)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if !enabled {
                    let names = inventory.supported.map(\.name)
                    if !names.isEmpty { caption(Copy.SaveWhy.willWatch(names)) }
                } else {
                    let status = status
                    ForEach(SaveWhySetup.lines(enabled: enabled, status: status), id: \.self) { caption($0) }
                    // G191 v3 — what Cicada watches to ask at once, in plain words.
                    if status.watching.contains("Chrome") { caption(Copy.SaveWhy.bubbleLine) }
                    if !status.needsFullDiskAccess.isEmpty {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            NeutralButton(title: Copy.SaveWhy.openFullDiskAccess, size: .compact) {
                                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
                            }
                            TextButton(title: Copy.SaveWhy.checkAgain, help: Copy.SaveWhy.checkAgain) {
                                for channel in SaveWhySetup.channels(inventory: inventory)
                                where watcher.state(for: channel) == .blocked { watcher.enable(channel) }
                            }
                        }
                    }
                }
                if muted > 0 {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        caption(Copy.SaveWhy.mutedLine(muted))
                        TextButton(title: Copy.SaveWhy.unmuteAll, help: Copy.SaveWhy.unmuteAll) {
                            prefs.mutedHosts = []
                            muted = 0
                        }
                    }
                }
            }
        }
        .onAppear { muted = prefs.mutedHosts.count }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
