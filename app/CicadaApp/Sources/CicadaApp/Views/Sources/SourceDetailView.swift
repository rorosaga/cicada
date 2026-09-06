import SwiftUI

/// One source's page (G124). A harness shows its conversations; every other
/// kind shows its channel state, folder counts and items. Back is a chevron
/// and ⌘[ (R15) — the same key the entity card uses on the Graph tab, which
/// is never mounted at the same time as this view.
///
/// The header (Track D) leads with the source's own mark and one honest
/// sentence of what Cicada reads from it (`SourceBlurb`); `SourceHeaderCard`
/// under it repeats the grid tile's own five facts at page scale — the brand,
/// the liveness sentence with the WHOLE error rather than its first clause, and
/// the 30-day line with the same two nouns (R-S7) — and the queue strip under
/// THAT says what's waiting and what has already been folded in.
struct SourceDetailView: View {
    let source: SourceOverview
    let onBack: () -> Void
    var onSelectEntity: ((String) -> Void)?

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store
    @Environment(BrowserWatcher.self) private var watcher
    @State private var loadedOnce = false

    /// `source` is a snapshot captured at navigation time (`SourcesPageView`'s
    /// `route` holds it in a plain `let`), so after a Consolidate run its counts
    /// are stale while the strip below has already moved. Re-resolve by id on
    /// every render — the same reason, and the same fallback, as
    /// `SourceQueueStrip.liveSource`.
    private var live: SourceOverview {
        store.sourcesOverview.value?.first(where: { $0.id == source.id }) ?? source
    }

    /// The ONE place this page talks to `BrowserWatcher` or reads a clock; the
    /// header card is a plain value view over what this resolves (the same split
    /// `SourceCardTile`/`SourceCard` draws on the grid).
    private var headerCard: some View {
        let row = live
        let today = Date()
        let watchState = row.channelId.flatMap { watcher.state(for: $0) }
        return SourceHeaderCard(
            source: row,
            // `channel: nil` — `build_overview` already copies the channel's
            // `actions` onto the row, so no `store.channels` join is needed.
            liveness: SourceLiveness.of(row: row, channel: nil, watch: watchState),
            // R-S8: Track A's window function, called where it lives, over the
            // whole 30 days the payload carries.
            points: sparklinePoints(activity: row.activity,
                                    days: SourceCardMetrics.detailSparkDays, today: today),
            today: today,
            watchState: watchState)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: source.label, subtitle: SourceBlurb.text(for: source),
                       leading: AnyView(OriginMark(origin: source.mark, size: 28))) {
                Button(action: onBack) {
                    Label("Sources", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all sources (⌘[)")
                .accessibilityLabel("Back to all sources")
            }
            headerCard
            SourceQueueStrip(source: source)
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
        // sleepVM.queuedEpisodes must be populated for the strip above even
        // when Sources is opened without ever visiting Sleep first this
        // session — mirrors SleepView's own `loadedOnce` guard.
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
            }
        }
    }
}
