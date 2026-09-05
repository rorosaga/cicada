import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll"),
/// grouped into sections by kind (Track D) so seventeen-odd sources read as
/// a handful of short, labelled groups instead of one long shuffled list.
///
/// **Sources v2 (R-S1)** — every section shares ONE column count, derived from
/// the container width in *scaled* units. Before this the grid was
/// `.adaptive(minimum: 220, maximum: 320)`: two raw points in a card whose
/// every font and spacing token goes through `CicadaTheme.scaled`, so at ⌘+
/// the text grew 40 % and the column did not (critique C2), and `.adaptive`
/// with `alignment: .leading` left a card-shaped hole at the end of any short
/// section (C3). `.flexible()` × a computed count fixes both, and — with every
/// tile at `SourceCardMetrics.tileHeight` — also retires the "Files & links
/// offset" (C1): a `LazyVGrid` row is as tall as its tallest card and centres
/// the shorter ones, so cards of equal height cannot misalign.
///
/// The width is measured through a background `GeometryReader` + preference
/// (the pattern `DiffView` already uses) rather than by WRAPPING the sections
/// in a `GeometryReader`: a `GeometryReader` inside this page's `ScrollView`
/// reports the viewport height as its own and would clip the grid to one
/// screen. Same single reading, no layout damage.
///
/// Never-loaded → skeleton tiles at the real height and the real column count
/// (a page that already knows its shape should draw it, not replace itself
/// with a centred spinner); loaded-but-empty → the one call to action (R2: a
/// row is shown only when it has evidence); otherwise one section per
/// non-empty kind. `isRefreshing` is gone (R-S10) — it was read by nothing,
/// and the never-blank rule already means the grid shows last-known-good all
/// the way through a refresh.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let onOpen: (SourceOverview) -> Void

    /// 0 until the first layout pass; `SourceGridColumns.count` floors at 2, so
    /// the first frame draws a valid grid rather than a crash or a blank.
    @State private var containerWidth: CGFloat = 0

    private var columnCount: Int {
        SourceGridColumns.count(width: containerWidth, scale: CicadaTheme.uiScale)
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingMD), count: columnCount)
    }

    var body: some View {
        Group {
            if !hasLoaded {
                skeleton
            } else if rows.isEmpty {
                EmptyStateView(
                    title: "Nothing here yet",
                    message: Copy.emptySourcesMessage,
                    actionLabel: "Add a source",
                    settingsSection: .integrations
                )
            } else {
                // ONE `today` per body evaluation, handed down to every tile,
                // so two cards can never straddle a UTC midnight inside one
                // render — the same posture `MemorySourcesCard` holds.
                let today = Date()
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(SourceSections.group(rows), id: \.kind) { section in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            Text(section.title)
                                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .tracking(1.2)
                            LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                ForEach(section.rows) { row in
                                    SourceCardTile(source: row, today: today, onOpen: { onOpen(row) })
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .background(
            GeometryReader { proxy in
                Color.clear.preference(key: SourceGridWidthKey.self, value: proxy.size.width)
            }
        )
        .onPreferenceChange(SourceGridWidthKey.self) { containerWidth = $0 }
    }

    /// Six placeholder tiles — the real height, the real columns, no motion.
    /// A centred "Reading your sources…" spinner replaced the whole page with
    /// something that looked like a different screen; this one looks like the
    /// screen that is about to arrive.
    private var skeleton: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(0..<6, id: \.self) { _ in
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .fill(CicadaTheme.textTertiary.opacity(0.08))
                    .frame(height: SourceCardMetrics.tileHeight)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Reading your sources")
    }
}

/// The measured width of the grid's container. `max` on reduce because the
/// background publishes exactly one value; the reducer only has to be
/// well-defined.
private struct SourceGridWidthKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// How a liveness tone paints. Four tones, not nine colours: the verb carries
/// the meaning and the tone carries only "fine / act / broken / dormant"
/// (R-S2). Lives here rather than on `SourceLiveness` so that type stays a
/// pure, `SwiftUI`-colour-free decision the tests can table-drive.
extension SourceLiveness.Tone {
    var color: Color {
        switch self {
        case .live: CicadaTheme.success
        case .warning: CicadaTheme.warning
        case .danger: CicadaTheme.danger
        case .dormant: CicadaTheme.textTertiary.opacity(0.5)
        }
    }
}

/// One card plus its quick action, as sibling views in a `ZStack` rather than
/// a button nested inside a button (R-D2: the two hit test independently, so
/// tapping the small action can never also open the page). Owns its own
/// `hovering`/`busy` state — one instance per row, so a spinner on one card
/// never bleeds into its neighbours.
///
/// **D4 — the action is always in the hierarchy**, faded rather than absent.
/// Mounting it `if hovering` kept it out of the tab order and out of
/// VoiceOver entirely, so the only way to sync a source without opening its
/// page was to be holding a pointer. It now fades in on hover OR keyboard
/// focus, and the tile carries an `.accessibilityAction` for the same work.
///
/// **D5 — `busy` is cleared AFTER the refresh**, not before it. The old order
/// (`busy = false` then `await store.refresh(...)`) re-enabled the button
/// while the round-trip was still in flight, so a second click could start a
/// second sync of the same channel.
private struct SourceCardTile: View {
    let source: SourceOverview
    /// Resolved once by the grid, never by the tile — see `SourceCardGrid`.
    let today: Date
    let onOpen: () -> Void

    @Environment(Store.self) private var store
    @Environment(BrowserWatcher.self) private var watcher
    @State private var hovering = false
    @State private var busy = false
    @FocusState private var actionFocused: Bool

    private var watchState: BrowserWatchState? {
        source.channelId.flatMap { watcher.state(for: $0) }
    }
    private var watchError: BrowserFileError? {
        source.channelId.flatMap { watcher.error(for: $0) }
    }

    /// `channel: nil` on purpose: `source_overview.build_overview` already
    /// copies the channel's `actions` onto the row, so the grid needs no
    /// `store.channels` join. The parameter exists for the detail page and for
    /// a caller that has a channel in hand.
    private var liveness: SourceLiveness {
        SourceLiveness.of(row: source, channel: nil, watch: watchState)
    }

    /// R-S8 — Track A's window functions, called where they live. No alias, no
    /// wrapper, no second spelling of the same 14 days.
    private var points: [Int] {
        sparklinePoints(activity: source.activity, days: SourceCardMetrics.sparkDays, today: today)
    }
    private var dots: [Int] {
        weekDots(activity: source.activity, weeks: SourceCardMetrics.weeks, today: today)
    }

    var body: some View {
        // The action is registered on the TILE, not only on the button, so a
        // VoiceOver user reaches it from the card itself (D4). A row with no
        // channel action registers none — an action named after work this row
        // cannot do is worse than no action at all.
        if let action = SourceCard.quickAction(for: source) {
            stack(action).accessibilityAction(named: Text(action)) { run(action) }
        } else {
            stack(nil)
        }
    }

    private func stack(_ action: String?) -> some View {
        ZStack(alignment: .topTrailing) {
            Button(action: onOpen) {
                SourceCard(source: source, liveness: liveness, points: points, dots: dots,
                           delta: SourceDeltaText.text(points: points,
                                                       lastActivity: source.lastActivityDate,
                                                       today: today),
                           watchState: watchState, watchError: watchError)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: watchState))

            if let action {
                quickActionButton(action)
                    .padding(CicadaTheme.spacingSM)
                    .opacity(hovering || actionFocused ? 1 : 0)
            }
        }
        .onHover { hovering = $0 }
    }

    private func quickActionButton(_ title: String) -> some View {
        Button(title) { run(title) }
            .buttonStyle(.bordered).controlSize(.mini).disabled(busy)
            .focused($actionFocused)
            .accessibilityLabel(title)
    }

    private func run(_ title: String) {
        guard let channelId = source.channelId, !busy else { return }
        Task {
            busy = true
            // R-D5: best-effort. The card has no room for an error line; the
            // identical action's failure (and `lastError`) is one click away on
            // the detail page — and now, since R-S2, its first clause is on the
            // card's own status band.
            _ = try? await (title == "Poll now" ? ChannelActions.poll(channelId)
                                                 : ChannelActions.sync(channelId, store: store))
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
            busy = false
        }
    }
}

/// One card, five bands on a fixed-height tile (R-S1 … R-S4):
///
/// 1. the mark and the **brand** name (`SourceDisplayName`, R-S4 — never the
///    catalog's long `label`, which truncated to "Chrome bookm…", A1);
/// 2. the status band — the G129 light where a browser watch exists, else a
///    dot tinted by the liveness tone, followed by the one verb that names
///    what this source is actually doing (R-S2/D1: the old dot was
///    `source.connected`, which `build_overview` sets to `episodes > 0`, so a
///    live-watched Chrome and a July import painted the same green);
/// 3. the 14-day capture sparkline beside the LIFETIME total in the row's own
///    unit (R-S3 — two nouns, so 506 bookmarks never read as 506 recent
///    captures);
/// 4. four week-dots beside the delta sentence (D3 — nothing on the old card
///    said whether the number was still growing).
///
/// `watchState`/`watchError` and every derived series are passed in rather
/// than read from the environment or a clock, so the card stays a plain,
/// previewable value view — `SourceCardTile` is the one place that talks to
/// `BrowserWatcher` and the one place that resolves `today`.
struct SourceCard: View {
    let source: SourceOverview
    let liveness: SourceLiveness
    let points: [Int]
    let dots: [Int]
    let delta: String
    var watchState: BrowserWatchState? = nil
    var watchError: BrowserFileError? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            nameBand
            statusBand
            Spacer(minLength: 0)
            volumeBand
            rhythmBand
        }
        .frame(maxWidth: .infinity, minHeight: SourceCardMetrics.tileHeight,
               maxHeight: SourceCardMetrics.tileHeight, alignment: .topLeading)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var nameBand: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            OriginMark(origin: source.mark, size: SourceCardMetrics.markSize * 0.72)
                .frame(width: SourceCardMetrics.markSize, height: SourceCardMetrics.markSize)
                .background(OriginIconography.color(for: source.mark).opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.scaled(6)))
            Text(SourceDisplayName.of(source))
                .font(CicadaTheme.font(size: 14, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
    }

    /// D2 — the reason a source is broken belongs ON the card. The old card
    /// said "Needs attention" and hid the message in a tooltip; the verb now
    /// folds in the error's first clause and `.help` still carries the whole
    /// message, so nothing is lost and the card stops being a riddle.
    private var statusBand: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            // R-S11: where a `BrowserWatchState` exists the G129 light is
            // reused byte-for-byte (R-D6); everywhere else the dot is tinted by
            // the liveness tone, never by `connected` — "has ever fed memory"
            // is why the row exists (G124 R2), not what it is doing.
            if let watchState {
                BrowserStatusLight(state: watchState, error: watchError, compact: true)
            } else {
                Circle().fill(liveness.tone.color).frame(width: 7, height: 7)
            }
            Text(liveness.verb)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(liveness.tone == .danger ? CicadaTheme.danger : CicadaTheme.textSecondary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .help(source.lastError ?? liveness.verb)
    }

    private var volumeBand: some View {
        HStack(alignment: .lastTextBaseline, spacing: CicadaTheme.spacingSM) {
            sparkline
            Spacer(minLength: 0)
            if let headline = source.headline {
                HStack(alignment: .firstTextBaseline, spacing: 3) {
                    Text(UsageFormat.count(headline.count))
                        .font(CicadaTheme.font(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(headline.count == 1 ? headline.noun : headline.noun + "s")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .lineLimit(1)
            } else {
                Text("Nothing yet")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    /// Decorative in the accessibility sense — `accessibilityLabel(for:)`
    /// carries the number, and R-A13's motion budget means it never animates.
    private var sparkline: some View {
        GeometryReader { geo in
            sparklinePath(points, in: geo.size)
                .stroke(liveness.tone.color.opacity(0.8),
                        style: StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round))
        }
        .frame(width: CicadaTheme.scaled(56), height: CicadaTheme.scaled(16))
        .accessibilityHidden(true)
    }

    private var rhythmBand: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // State, not quantity — the sparkline already encodes how much, so
            // a second graded mark twelve points away would ask the reader to
            // tell two charts apart by weight (G125 R1, as `MemorySourcesCard`
            // reads it).
            HStack(spacing: 3) {
                ForEach(Array(dots.enumerated()), id: \.offset) { _, count in
                    Circle()
                        .fill(count > 0 ? liveness.tone.color.opacity(0.65) : CicadaTheme.border)
                        .frame(width: 4, height: 4)
                }
            }
            Text(delta)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(delta)
    }

    /// Which quick action, if any, the card offers — sync wins when a row
    /// somehow advertises both (R-D3: no catalog row does today).
    static func quickAction(for source: SourceOverview) -> String? {
        if source.actions.contains("sync") { return "Sync now" }
        if source.actions.contains("poll") { return "Poll now" }
        return nil
    }

    /// The card's accessibility label, with the status light's own title
    /// appended when one is shown — the rail is "keep the accessibility
    /// label and GAIN the state title", not replace one with the other.
    ///
    /// R-S4: it leads with the same brand the card prints, not the catalog's
    /// long `label`. VoiceOver and the eye must name a source identically, or
    /// the page has two names for one row.
    static func accessibilityLabel(for source: SourceOverview, watchState: BrowserWatchState?) -> String {
        var label = "\(SourceDisplayName.of(source)), \(source.countLines.joined(separator: ", "))"
        if let watchState { label += ", \(BrowserStatusLight.title(for: watchState))" }
        return label
    }
}
