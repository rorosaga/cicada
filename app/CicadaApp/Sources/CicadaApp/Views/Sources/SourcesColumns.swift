import SwiftUI

/// What Sources' detail column holds: a source, or one author of the bank (R-DL22).
enum SourcesSelection: Hashable {
    case source(String)
    case contributor(String)
}

/// R-DL26 / R-DL6 — Sources' words and order, pure.
enum SourcesModel {
    typealias Section = (kind: SourceKind, title: String, rows: [SourceOverview])

    /// The rows ↑/↓ walk, in the order the list draws them: every section's sources, then the named contributors.
    static func order(sections: [Section], authors: [String]) -> [SourcesSelection] {
        sections.flatMap { $0.rows.map { SourcesSelection.source($0.id) } } + authors.map(SourcesSelection.contributor)
    }

    /// Everything the detail column can still show — a selection outside it has left the data (R-DL6).
    static func present(rows: [SourceOverview], contributors: [Contributor]) -> Set<SourcesSelection> {
        Set(rows.map { SourcesSelection.source($0.id) })
            .union(contributors.map { SourcesSelection.contributor($0.author) })
    }

    /// DR-25 — "Sources · 7 connected" / "Sources · 2 of 7 · Browsers" / "Sources · Who wrote your memory".
    static func eyebrow(sections: [Section], open: SourcesSelection?) -> String {
        let ordered = sections.flatMap(\.rows)
        let overview = Eyebrow.text(Copy.sources, ordered.isEmpty ? "" : Copy.Lists.connected(ordered.count))
        switch open {
        case .contributor?:
            return Eyebrow.text(Copy.sources, Copy.Lists.whoWrote)
        case .source(let id)?:
            guard let i = ordered.firstIndex(where: { $0.id == id }),
                  let section = sections.first(where: { $0.rows.contains { $0.id == id } }) else { return overview }
            return Eyebrow.text(Copy.sources, Copy.Inbox.position(i + 1, of: ordered.count), section.title)
        case nil:
            return overview
        }
    }

    /// A contributor's share of entities written, from the strip's own segments (one scale, R-S6).
    static func share(of author: String, in segments: [ContributorShare.Segment]) -> Double? {
        segments.first { $0.author == author && !$0.isRemainder }?.fraction
    }
}

/// R-DL19 / P4 — sections share a row. A section spans as many columns as it has tiles (never more than the grid has),
/// sits beside the one before it while their spans fit, and one with more tiles than columns takes whole rows by
/// itself — so a one-tile section no longer leaves two thirds of its row empty. The approved mock's packing, pure.
enum SourceGridPacking {
    struct Placement: Equatable {
        let section: Int
        let span: Int
    }

    static func rows(tileCounts: [Int], columns: Int) -> [[Placement]] {
        let columns = max(columns, 1)
        var rows: [[Placement]] = []
        var used = 0
        for (index, count) in tileCounts.enumerated() where count > 0 {
            let span = min(count, columns)
            if rows.isEmpty || used + span > columns || count > columns {
                rows.append([])
                used = 0
            }
            rows[rows.count - 1].append(Placement(section: index, span: span))
            used = count > columns ? columns : used + span
        }
        return rows
    }

    /// The contributors block joins the last row when it leaves two columns or more; otherwise it takes a full row.
    static func contributorsSpan(rows: [[Placement]], columns: Int) -> (joinsLastRow: Bool, span: Int) {
        let used = rows.last.map { $0.reduce(0) { $0 + $1.span } } ?? columns
        let left = columns - used
        return left >= 2 ? (true, left) : (false, columns)
    }
}

/// STATE 0 — the grid (sparse tiles, reached with Tab), the contributors block and the Advanced disclosure.
struct SourcesOverviewColumn: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let onOpen: (SourcesSelection) -> Void
    var onSelectEntity: ((String) -> Void)?

    @Environment(UsageViewModel.self) private var usageVM

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                SourceCardGrid(rows: rows, hasLoaded: hasLoaded, onOpen: { onOpen(.source($0.id)) }) {
                    ContributorsStrip { onOpen(.contributor($0.author)) }
                }
                advanced
            }
            .padding(.bottom, CicadaTheme.scaled(72))
        }
    }

    /// R-DL23 (DR-39) — the header's Advanced toggle became this remembered disclosure, on the same
    /// `cicada.usageMode` key, so an existing choice carries over.
    private var advanced: some View {
        let isOpen = usageVM.mode == .advanced
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Button { usageVM.mode = isOpen ? .minimal : .advanced } label: {
                HStack(spacing: CicadaTheme.scaled(6)) {
                    Image(systemName: isOpen ? "chevron.down" : "chevron.right").font(CicadaTheme.icon(.inline))
                    Text(Copy.Lists.advancedStatistics)
                }
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(height: CicadaTheme.scaled(28))
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.Lists.advancedHelp)
            .accessibilityValue(isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed)
            .padding(.horizontal, CicadaTheme.spacingGutter)
            if isOpen { AdvancedStatsView(onSelectEntity: onSelectEntity) }
        }
    }
}

/// STATE 1 / 2 — the sources as rows (sections by kind), then who wrote the bank.
struct SourcesListColumn: View {
    let sections: [SourcesModel.Section]
    let segments: [ContributorShare.Segment]
    let style: ColumnPlan.ListStyle
    let selection: SourcesSelection?
    let open: (SourcesSelection) -> Void
    let move: (Int) -> Void
    let escape: () -> Void

    @Environment(BrowserWatcher.self) private var watcher

    var body: some View {
        let today = Date()
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading,
                       spacing: style == .triage ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                    ForEach(sections, id: \.kind) { section in
                        label(section.title)
                        ForEach(section.rows) { row in
                            let points = sparklinePoints(activity: row.activity, days: SourceCardMetrics.sparkDays,
                                                         today: today)
                            SourceListRow(source: row,
                                          liveness: SourceLiveness.of(row: row, channel: nil,
                                                                      watch: row.channelId.flatMap { watcher.state(for: $0) }),
                                          delta: SourceDeltaText.text(points: points, lastActivity: row.lastActivityDate,
                                                                      today: today),
                                          style: style, selected: selection == .source(row.id)) {
                                open(.source(row.id))
                            }
                            .id(SourcesSelection.source(row.id))
                        }
                    }
                    let named = segments.filter { !$0.isRemainder }
                    if !named.isEmpty {
                        label(Copy.Lists.whoWrote)
                        ForEach(named) { segment in
                            ContributorListRow(segment: segment, style: style,
                                               selected: selection == .contributor(segment.author)) {
                                open(.contributor(segment.author))
                            }
                            .id(SourcesSelection.contributor(segment.author))
                        }
                    }
                }
                .padding(ListInsets.of(style))
            }
            .onChange(of: selection) { _, s in
                guard let s else { return }
                Instant.run { proxy.scrollTo(s) }
            }
        }
        .listKeys(move: move, enter: { false }, escape: escape)
    }

    private func label(_ title: String) -> some View {
        SectionLabel(title)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.top, CicadaTheme.scaled(14))
            .padding(.bottom, CicadaTheme.scaled(4))
    }
}

/// One source as a row: the bare mark (DR-52), the brand, its total in its own unit; the verb and the delta under it —
/// the tile's facts at list density (R-S19: one projection, many renderings).
struct SourceListRow: View {
    let source: SourceOverview
    let liveness: SourceLiveness
    let delta: String
    let style: ColumnPlan.ListStyle
    let selected: Bool
    let open: () -> Void

    private var metaColor: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }

    var body: some View {
        Button(action: open) {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: ListRowSurface.height(style), selected: selected)
        .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: nil))
        .accessibilityAddTraits(selected ? .isSelected : [])
        .help(SourceCardText.rowDetail(liveness: liveness, delta: delta))
    }

    private var name: some View {
        Text(SourceDisplayName.of(source))
            .font(CicadaTheme.font(size: 13, weight: selected ? .medium : .regular))
            .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .lineLimit(1)
    }

    @ViewBuilder
    private var content: some View {
        switch style {
        case .triage, .wide:
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                OriginMark(origin: source.mark, size: CicadaTheme.scaled(14)).padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        name
                        Spacer(minLength: 0)
                        if let headline = source.headline {
                            Text(Copy.Lists.headline(headline.count, noun: headline.noun))
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(metaColor)
                                .lineLimit(1)
                        }
                    }
                    Text(SourceCardText.rowDetail(liveness: liveness, delta: delta))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(liveness.tone.isAlarm && !selected ? CicadaTheme.warning : metaColor)
                        .lineLimit(1)
                }
            }
        case .titles, .hidden:
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: CicadaTheme.scaled(14))
                name
            }
        }
    }
}

/// One author of the bank as a row: the real mark (`ContributorAvatar`, R-S14), the name, the share; commits under it.
struct ContributorListRow: View {
    let segment: ContributorShare.Segment
    let style: ColumnPlan.ListStyle
    let selected: Bool
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(alignment: style == .triage ? .top : .center, spacing: CicadaTheme.scaled(10)) {
                if let c = segment.contributor {
                    ContributorAvatar(contributor: c, kind: ContributorIdentity.kind(of: c), size: CicadaTheme.scaled(14))
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(segment.displayName)
                            .font(CicadaTheme.font(size: 13, weight: selected ? .medium : .regular))
                            .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                            .lineLimit(1)
                        Spacer(minLength: 0)
                        if style == .triage {
                            Text(UsageFormat.percent(segment.fraction * 100))
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                    if style == .triage, let c = segment.contributor {
                        Text(Eyebrow.text(Copy.Lists.commits(c.commitCount), Copy.Lists.shareOfEntities))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .listRowSurface(height: ListRowSurface.height(style), selected: selected)
        .help(segment.author)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
