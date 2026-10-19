import SwiftUI

/// Sources v4 (owner 2026-10-19: "remove the graph and just put what the source is. Avoid repetition. There's so much
/// repetition." … "just have a 'Consolidate now' button at the top, with how many things are pending from that
/// category, as a small notification") — the words of a source's one header, pure and tested without a view.
enum SourceDetailText {
    /// The header's state line: what the source is doing and when it last synced, said once. A failure says its WHOLE
    /// error (the row beside it has room for a clause only, D2); a run in progress says so; otherwise the liveness verb
    /// and the channel's own "Last synced …" / "Imported …", never the same fact twice ("Syncing… · Syncing now").
    static func state(liveness: SourceLiveness, status: SourceRowStatus, fullError: String?, now: Date,
                      locale: Locale = .autoupdatingCurrent) -> (text: String, isAlarm: Bool) {
        if case .problem(let why) = status { return (why, true) }
        if liveness.tone.isAlarm { return (sentence(liveness: liveness, fullError: fullError), true) }
        switch status {
        case .syncing: return (Copy.syncingNow, false)
        case .synced, .imported, .notYet:
            let when = SourceRowText.trailing(status, now: now, locale: locale) ?? ""
            // A one-shot import's "Imported once" and its "Imported 3 days ago" are one fact: the dated one wins.
            if case .imported = status { return (when, false) }
            return (Eyebrow.text(liveness.verb, when), false)
        case .idle, .problem:
            return (liveness.verb, false)
        }
    }

    /// The liveness verb around the untruncated error (the tile's verb, so the two never name a failure two ways). A
    /// blank or absent error is no error, so the verb is returned as-is — never a dangling em dash.
    static func sentence(liveness: SourceLiveness, fullError: String?) -> String {
        let full = fullError?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !full.isEmpty else { return liveness.verb }
        return SourceLiveness(state: liveness.state, detail: full).verb
    }

    /// "Consolidate now · 2 waiting" — the small control at the top of a source with something waiting; nil (no
    /// control) when nothing from this source waits and no read is running.
    static func consolidate(waiting: Int, running: Bool) -> String? {
        if running { return Copy.consolidating }
        guard waiting > 0 else { return nil }
        return Eyebrow.text(Copy.consolidateNow, "\(UsageFormat.count(waiting)) waiting")
    }
}

/// Sources v4 — a source's one header: the bare mark (DR-52), the name as the detail heading, what the source is in one
/// line (`SourceBlurb`), then one state line — its live state and last sync, with Sync now inline (DR-40) — and, only
/// when something from this source waits for Sleep, "Consolidate now · N waiting" as a compact neutral button (DR-40,
/// DR-51: the count is words in the control, never a badge). It replaces v3's 30-day card, its sparkline and delta,
/// the queue strip and its "Consolidated so far" line, and the sync card that repeated the name a third time (DR-38).
struct SourceDetailHead: View {
    let source: SourceOverview
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(SyncActivity.self) private var activity: SyncActivity?
    @Environment(LocalSourceWatcher.self) private var localSources: LocalSourceWatcher?
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(WatchHistoryWatcher.self) private var watchHistory: WatchHistoryWatcher?
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @Environment(ContactsReader.self) private var contacts: ContactsReader?
    @State private var busy = false
    @State private var feedback: ChannelFeedback?

    private var channel: SourceChannel? {
        guard let id = source.channelId else { return nil }
        return (store.channels.value ?? []).first { $0.id == id }
    }

    /// The title's left edge: the mark (20) and the header's gap, so the state line sits under the name.
    private var indent: CGFloat { CicadaTheme.scaled(20) + CicadaTheme.spacingMD }

    var body: some View {
        let watch = source.channelId.flatMap { watcher.state(for: $0) }
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            DetailHeader(title: SourceDisplayName.of(source), blurb: SourceBlurb.text(for: source),
                         backLabel: hiddenListCount.map(Copy.Lists.sourcesBack), onShowList: onShowList,
                         closeHelp: Copy.Lists.closeSource,
                         closeShortcut: KeyboardShortcut("[", modifiers: .command), onClose: onClose) {
                OriginMark(origin: source.mark, size: CicadaTheme.scaled(20)).markHover()
            }
            TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                stateLine(watch: watch, now: context.date)
            }
            .padding(.leading, indent)
            // R-D6 kept: the Full Disk Access fix is shown exactly where the read failed.
            if watch == .blocked, let id = source.channelId, let error = watcher.error(for: id) {
                FullDiskAccessHint(error: error).padding(.leading, indent)
            }
            if let feedback {
                Text(feedback.text).font(CicadaTheme.captionFont)
                    .foregroundStyle(feedback.isError ? CicadaTheme.danger : CicadaTheme.success)
                    .padding(.leading, indent)
                    .task(id: feedback) {
                        try? await Task.sleep(for: .seconds(5))
                        if !Task.isCancelled { self.feedback = nil }
                    }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.bottom, CicadaTheme.spacingMD)
    }

    private func stateLine(watch: BrowserWatchState?, now: Date) -> some View {
        let liveness = SourceLiveness.of(row: source, channel: channel, watch: watch)
        let run = channel.flatMap { activity?.run(for: $0.id) }
        let status = channel == nil ? SourceRowStatus.idle
            : SourceRowText.status(channel: channel, watch: watch, run: run)
        let state = SourceDetailText.state(liveness: liveness, status: status, fullError: source.lastError, now: now)
        return HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            if case .syncing = status {
                ProgressView().controlSize(.small)
            } else if !state.isAlarm, liveness.tone.showsDot {
                Circle().fill(liveness.tone.color)
                    .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
            }
            Text(state.text)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(state.isAlarm ? CicadaTheme.warning : CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .help(state.text)
            if case .syncing(_, _, true) = status, let id = channel?.id {
                IconButton(systemName: "xmark", help: Copy.stopSyncingHelp,
                           accessibilityLabel: "\(Copy.stopSyncing), \(source.label)") { activity?.cancel(id) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let channel {
                if channel.actions.contains("sync"), let localSources {
                    actionButton("Sync now") {
                        try await ChannelActions.sync(channel.id, store: store, watcher: watcher, local: localSources,
                                                      calendar: calendarReader, tabGroups: tabGroups,
                                                      contacts: contacts, messages: messages, watchHistory: watchHistory)
                    }
                }
                if channel.actions.contains("poll") {
                    actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
                }
            }
            if let label = SourceDetailText.consolidate(waiting: source.waiting, running: sleepVM.isRunning) {
                NeutralButton(title: label, systemImage: "moon", size: .compact, isDisabled: sleepVM.isRunning,
                              help: Copy.consolidateSourceHelp, disabledHelp: Copy.consolidating) {
                    Task {
                        await sleepVM.triggerManually()
                        await store.refresh([.status, .channels, .sourcesOverview])
                    }
                }
                .accessibilityLabel(label)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
    }

    /// Every action refreshes the overview alongside the channel/items domains: the row's counts come from
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
}
