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
struct SourceCardGrid<Trailing: View>: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let onOpen: (SourceOverview) -> Void
    /// What follows the sections — the contributors block — so it can take the space the last row leaves (P4).
    @ViewBuilder let trailing: () -> Trailing

    /// 0 until the first layout pass; `SourceGridColumns.count` floors at 2, so
    /// the first frame draws a valid grid rather than a crash or a blank.
    @State private var containerWidth: CGFloat = 0
    /// Track I T5 (R-IA27) — the empty grid takes a dropped export itself.
    @Environment(IntakeRouter.self) private var intake

    private var columnCount: Int {
        SourceGridColumns.count(width: containerWidth, scale: CicadaTheme.uiScale)
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingMD), count: columnCount)
    }

    var body: some View {
        Group {
            if !hasLoaded {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) { skeleton; trailing() }
            } else if rows.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    EmptyStateView(
                        title: "Nothing here yet",
                        message: Copy.emptySourcesMessage,
                        actionLabel: "Add a source",
                        settingsSection: .integrations,
                        onDropFiles: { intake.accept(urls: $0, from: .emptyState(.sources)) }
                    )
                    trailing()
                }
            } else {
                packed
            }
        }
        // Fill the offered width BEFORE measuring: `packed` is fixed-width frames, so an unframed group would report
        // the width those frames were given — 0 on the first pass — and the grid would never grow out of it.
        .frame(maxWidth: .infinity, alignment: .topLeading)
        // The INNER width (measured before the gutter): both the column count and a span's width read it.
        .background(
            GeometryReader { proxy in
                Color.clear.preference(key: SourceGridWidthKey.self, value: proxy.size.width)
            }
        )
        .onPreferenceChange(SourceGridWidthKey.self) { containerWidth = $0 }
        .padding(.horizontal, CicadaTheme.spacingGutter)
    }

    private var gap: CGFloat { CicadaTheme.spacingMD }

    /// R-DL19 — a section spans `span` of the grid's columns; widths come from the one measured width.
    private func width(_ span: Int, columns: Int) -> CGFloat {
        let unit = max(0, (containerWidth - gap * CGFloat(columns - 1)) / CGFloat(columns))
        return unit * CGFloat(span) + gap * CGFloat(span - 1)
    }

    /// P4 — sections share a row (`SourceGridPacking`); the contributors block takes what the last row leaves when that
    /// is two columns or more. ONE `today` per body evaluation, handed to every tile (Sources v2's midnight rule).
    private var packed: some View {
        let today = Date()
        let cols = columnCount
        let sections = SourceSections.group(rows)
        let packedRows = SourceGridPacking.rows(tileCounts: sections.map(\.rows.count), columns: cols)
        let contributors = SourceGridPacking.contributorsSpan(rows: packedRows, columns: cols)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            ForEach(Array(packedRows.enumerated()), id: \.offset) { index, placements in
                HStack(alignment: .top, spacing: gap) {
                    ForEach(placements, id: \.section) { p in
                        section(sections[p.section].title, rows: sections[p.section].rows, span: p.span, today: today)
                            .frame(width: width(p.span, columns: cols), alignment: .topLeading)
                    }
                    if index == packedRows.count - 1 && contributors.joinsLastRow {
                        trailing().frame(width: width(contributors.span, columns: cols), alignment: .topLeading)
                    }
                }
            }
            if !contributors.joinsLastRow { trailing() }
        }
    }

    private func section(_ title: String, rows: [SourceOverview], span: Int, today: Date) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: gap), count: span),
                      alignment: .leading, spacing: gap) {
                ForEach(rows) { row in
                    SourceCardTile(source: row, today: today, onOpen: { onOpen(row) })
                }
            }
        }
    }

    /// Six placeholder tiles — the real height, the real columns, no motion.
    private var skeleton: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: gap) {
            ForEach(0..<6, id: \.self) { _ in
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .fill(CicadaTheme.bgSelected)
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

/// R-DL20 (DR-7) — four tones: live keeps `success` (the approved mock; dated in §9), a warning or a failure speaks in
/// `warning` — DR-7's "first clause of a failed source" — and `danger` stays for destructive actions only. A failing
/// source's verb says it in words, so its dot is hidden.
extension SourceLiveness.Tone {
    var color: Color {
        switch self {
        case .live: CicadaTheme.success
        case .warning, .danger: CicadaTheme.warning
        case .dormant: CicadaTheme.textQuaternary
        }
    }

    var showsDot: Bool { self == .live || self == .dormant }
    var isAlarm: Bool { self == .warning || self == .danger }
}

/// The tile's and the list row's words, one place (R-S19's rule: one projection, many renderings).
enum SourceCardText {
    static func noun(_ headline: (count: Int, noun: String)) -> String {
        headline.count == 1 ? headline.noun : headline.noun + "s"
    }

    /// A list row's second line: "Captured by hook · Nothing new since September".
    static func rowDetail(liveness: SourceLiveness, delta: String) -> String { Eyebrow.text(liveness.verb, delta) }

    /// Neutral text steps (P2): a flat line is `textQuaternary`, a dormant one `textTertiary`, a live one `textSecondary`.
    static func sparkColor(_ points: [Int], tone: SourceLiveness.Tone) -> Color {
        if points.allSatisfy({ $0 == 0 }) { return CicadaTheme.textQuaternary }
        return tone == .dormant ? CicadaTheme.textTertiary : CicadaTheme.textSecondary
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
    @Environment(CalendarReader.self) private var calendarReader: CalendarReader?
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var hovering = false
    @State private var busy = false
    @FocusState private var actionFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var watchState: BrowserWatchState? {
        source.channelId.flatMap { watcher.state(for: $0) }
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
                           delta: SourceDeltaText.text(points: points, lastActivity: source.lastActivityDate, today: today),
                           watchState: watchState, reservesAction: action != nil)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: watchState))

            if let action {
                // D4 — always in the hierarchy (tab order, VoiceOver), faded in on hover or focus. DR-40: neutral.
                NeutralButton(title: action, size: .compact, isDisabled: busy, help: action) { run(action) }
                    .focused($actionFocused)
                    .padding(.top, CicadaTheme.scaled(34))
                    .padding(.trailing, CicadaTheme.scaled(12))
                    .opacity(hovering || actionFocused ? 1 : 0)
            }
        }
        // DR-63 — a sparse tile that opens something: the strong ring and a 1 pt lift, never a scale or a shadow.
        .ringed(hovering ? .strong : .resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .offset(y: hovering && !reduceMotion ? -CicadaTheme.scaled(1) : 0)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onHover { hovering = $0 }
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
                                                 : ChannelActions.sync(channelId, store: store, watcher: watcher, local: localSources, calendar: calendarReader))
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
            busy = false
        }
    }
}

/// The five facts in D's material (R-DL19): the bare mark, brand and lifetime total; the verb; the week-dots, delta and
/// 14-day line. Sources v2's semantics hold (R-S1 … R-S4): the **brand** name (`SourceDisplayName`, R-S4), the one verb
/// that names what the source is doing (`SourceLiveness`, R-S2/D1), the LIFETIME total in the row's own unit beside a
/// line of CAPTURES (R-S3 — two nouns, so 506 bookmarks never read as 506 recent captures), and the week-dots beside
/// the delta (D3). The duplicate "Nothing yet" went: the delta already says it.
///
/// `watchState` and every derived series are passed in rather than read from the environment or a clock, so the card
/// stays a plain, previewable value view — `SourceCardTile` is the one place that talks to `BrowserWatcher` and the
/// one place that resolves `today`. No watch error travels here at all (R-DL21): the fix is the detail column's.
struct SourceCard: View {
    let source: SourceOverview
    let liveness: SourceLiveness
    let points: [Int]
    let dots: [Int]
    let delta: String
    var watchState: BrowserWatchState? = nil
    /// The quick action sits over the status line; its verb stops short of it.
    var reservesAction = false

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadius) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            nameBand
            statusBand
                .padding(.top, CicadaTheme.scaled(6))
                .padding(.trailing, reservesAction ? CicadaTheme.scaled(64) : 0)
            Spacer(minLength: 0)
            rhythmBand
        }
        .padding(EdgeInsets(top: CicadaTheme.scaled(14), leading: CicadaTheme.scaled(16),
                            bottom: CicadaTheme.scaled(13), trailing: CicadaTheme.scaled(16)))
        .frame(maxWidth: .infinity, minHeight: SourceCardMetrics.tileHeight, maxHeight: SourceCardMetrics.tileHeight,
               alignment: .topLeading)
        .background(shape.fill(CicadaTheme.bgFocus))
        // R-DL21 — nothing draws outside its tile, whatever a status sentence grows into.
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
        .contentShape(shape)
        .help(source.lastError ?? liveness.verb)
    }

    /// The mark stands bare (DR-52), the brand name (R-S4), and the LIFETIME total in the row's own unit (R-S3).
    private var nameBand: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            OriginMark(origin: source.mark, size: SourceCardMetrics.markSize)
            Text(SourceDisplayName.of(source))
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let headline = source.headline {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(4)) {
                    Text(UsageFormat.count(headline.count))
                        .font(CicadaTheme.font(size: 15, weight: .medium))
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(SourceCardText.noun(headline))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .lineLimit(1)
                .fixedSize()
            }
        }
        .frame(height: CicadaTheme.scaled(20))
    }

    /// R-S2 / R-S11 — the G129 light where a watch exists (dot only: `error: nil`, R-DL21), else the tone's dot, which a
    /// failure hides because its verb says it (R-DL20).
    private var statusBand: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            if let watchState {
                BrowserStatusLight(state: watchState, error: nil, compact: true, channelId: source.channelId)
            } else if liveness.tone.showsDot {
                Circle().fill(liveness.tone.color).frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
            }
            Text(liveness.verb)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(liveness.tone.isAlarm ? CicadaTheme.warning : CicadaTheme.textSecondary)
                .lineLimit(1)
        }
    }

    /// Four week-dots and the captures delta (R-S3, D3), then the 14-day line — all neutral (P2).
    private var rhythmBand: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.scaled(3)) {
                ForEach(Array(dots.enumerated()), id: \.offset) { _, count in
                    Circle()
                        .fill(count > 0 ? CicadaTheme.textSecondary : Color.clear)
                        .overlay(Circle().strokeBorder(count > 0 ? Color.clear : CicadaTheme.textQuaternary, lineWidth: 1))
                        .frame(width: CicadaTheme.scaled(5), height: CicadaTheme.scaled(5))
                }
            }
            .accessibilityHidden(true)
            Text(delta)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
            GeometryReader { geo in
                sparklinePath(points, in: geo.size)
                    .stroke(SourceCardText.sparkColor(points, tone: liveness.tone),
                            style: StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round))
            }
            .frame(width: CicadaTheme.scaled(64), height: CicadaTheme.scaled(16))
            .accessibilityHidden(true)
        }
        .accessibilityElement(children: .combine)
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
