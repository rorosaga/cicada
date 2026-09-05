import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll"),
/// grouped into sections by kind (Track D) so seventeen-odd sources read as
/// a handful of short, labelled groups instead of one long shuffled list.
/// Never-loaded → loading; loaded-but-empty → the one call to action (R2: a
/// row is shown only when it has evidence, and the Feed's `+` catalog is
/// where a person adds a source); otherwise one section per non-empty kind.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let isRefreshing: Bool
    let onOpen: (SourceOverview) -> Void

    private let columns = [GridItem(.adaptive(minimum: 220, maximum: 320), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        Group {
            if !hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sources…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if rows.isEmpty {
                EmptyStateView(
                    title: "Nothing here yet",
                    message: Copy.emptySourcesMessage,
                    actionLabel: "Add a source",
                    settingsSection: .integrations
                )
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(SourceSections.group(rows), id: \.kind) { section in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            Text(section.title)
                                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .tracking(1.2)
                            LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                ForEach(section.rows) { row in
                                    SourceCardTile(source: row, onOpen: { onOpen(row) })
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }
}

/// One card plus its hover-revealed quick action, as sibling views in a
/// `ZStack` rather than a button nested inside a button (R-D2: the two hit
/// test independently, so tapping the small action can never also open the
/// page). Owns its own `hovering`/`busy` state — one instance per row, so a
/// spinner on one card never bleeds into its neighbours.
private struct SourceCardTile: View {
    let source: SourceOverview
    let onOpen: () -> Void

    @Environment(Store.self) private var store
    @Environment(BrowserWatcher.self) private var watcher
    @State private var hovering = false
    @State private var busy = false

    private var watchState: BrowserWatchState? {
        source.channelId.flatMap { watcher.state(for: $0) }
    }
    private var watchError: BrowserFileError? {
        source.channelId.flatMap { watcher.error(for: $0) }
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Button(action: onOpen) {
                SourceCard(source: source, watchState: watchState, watchError: watchError)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: watchState))

            if hovering, let action = SourceCard.quickAction(for: source) {
                quickActionButton(action)
                    .padding(CicadaTheme.spacingSM)
            }
        }
        .onHover { hovering = $0 }
    }

    private func quickActionButton(_ title: String) -> some View {
        Button(title) {
            guard let channelId = source.channelId else { return }
            Task {
                busy = true
                // R-D5: best-effort. The card has no room for an error line;
                // the identical action's failure (and `lastError`) is one
                // click away on the detail page.
                _ = try? await (title == "Poll now" ? ChannelActions.poll(channelId)
                                                     : ChannelActions.sync(channelId, store: store))
                busy = false
                await store.refresh([.channels, .sources, .sourcesOverview, .status])
            }
        }
        .buttonStyle(.bordered).controlSize(.mini).disabled(busy)
        .accessibilityLabel(title)
    }
}

/// One card: mark, label, the counts that apply, last activity, state. The
/// mark reuses `OriginMark` (Track D) — the same bundled-logo → drawn-glyph →
/// SF-Symbol precedence the Sleep queue and the import catalog already draw.
/// `watchState`/`watchError` are passed in rather than read from the
/// environment here, so the card stays a plain, previewable value view —
/// `SourceCardTile` is the one place that talks to `BrowserWatcher`.
struct SourceCard: View {
    let source: SourceOverview
    var watchState: BrowserWatchState? = nil
    var watchError: BrowserFileError? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: 20)
                    .frame(width: 24, height: 24)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(source.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
                // G129's status light where a watch exists; the plain dot
                // everywhere else — unchanged from before G129 (R-D6: the
                // light is reused exactly as it renders on ChannelSourceView,
                // .blocked's FullDiskAccessHint included).
                if let watchState {
                    BrowserStatusLight(state: watchState, error: watchError, compact: true)
                } else {
                    Circle().fill(source.connected ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.4))
                        .frame(width: 7, height: 7)
                        .help(source.connected ? "Connected" : "Not connected")
                }
            }
            ForEach(source.countLines, id: \.self) { line in
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let relative = relativeLastActivity {
                Text("Last \(relative)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let error = source.lastError, !error.isEmpty {
                Text("Needs attention").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger).help(error)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var relativeLastActivity: String? {
        guard let date = source.lastActivityDate else { return nil }
        let fmt = RelativeDateTimeFormatter(); fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }

    /// Which quick action, if any, a hover reveals — sync wins when a row
    /// somehow advertises both (R-D3: no catalog row does today).
    static func quickAction(for source: SourceOverview) -> String? {
        if source.actions.contains("sync") { return "Sync now" }
        if source.actions.contains("poll") { return "Poll now" }
        return nil
    }

    /// The card's accessibility label, with the status light's own title
    /// appended when one is shown — the rail is "keep the accessibility
    /// label and GAIN the state title", not replace one with the other.
    static func accessibilityLabel(for source: SourceOverview, watchState: BrowserWatchState?) -> String {
        var label = "\(source.label), \(source.countLines.joined(separator: ", "))"
        if let watchState { label += ", \(BrowserStatusLight.title(for: watchState))" }
        return label
    }
}
