import SwiftUI

/// What Sources' detail column holds: a source, or one author of the bank (R-DL22).
enum SourcesSelection: Hashable {
    case source(String)
    case contributor(String)
    /// G217 — a catalogue entry (`SourceCatalogEntry.id`).
    case entry(String)
}

/// Sources v3 (owner 2026-10-19: "The first screen answers 'where did my stuff come from'") — the page's two groups,
/// pure: what the person saved on purpose first, then what Cicada captures on its own (the backend's `intent`). Within
/// a group the newest activity leads, then the id, so the order never shuffles between reads. An empty group is not
/// drawn.
enum SourceIntentGroups {
    struct Group: Equatable {
        let intent: SourceIntent
        let title: String
        let rows: [SourceOverview]
    }

    static func title(_ intent: SourceIntent) -> String {
        switch intent {
        case .saved: Copy.Lists.savedByYou
        case .captured: Copy.Lists.capturedForYou
        }
    }

    static func group(_ rows: [SourceOverview]) -> [Group] {
        let ordered = rows.sorted { a, b in
            switch (a.lastActivityDate, b.lastActivityDate) {
            case let (l?, r?) where l != r: return l > r
            case (_?, nil): return true
            case (nil, _?): return false
            default: return a.id < b.id
            }
        }
        return SourceIntent.allCases.compactMap { intent in
            let inGroup = ordered.filter { $0.intent == intent }
            return inGroup.isEmpty ? nil : Group(intent: intent, title: title(intent), rows: inGroup)
        }
    }
}

/// R-DL26 / R-DL6 — Sources' words and order, pure.
enum SourcesModel {
    /// The rows ↑/↓ walk, in the order the list draws them: the saved group's sources, then the captured group's.
    /// Authors are not rows any more (Sources v3: who wrote the memory lives under Statistics), so they are not walked.
    static func order(groups: [SourceIntentGroups.Group]) -> [SourcesSelection] {
        groups.flatMap { $0.rows.map { SourcesSelection.source($0.id) } }
    }

    /// Everything the detail column can still show — a selection outside it has left the data (R-DL6).
    static func present(rows: [SourceOverview], contributors: [Contributor],
                        catalog: [SourceCatalogRow] = []) -> Set<SourcesSelection> {
        Set(rows.map { SourcesSelection.source($0.id) })
            .union(contributors.map { SourcesSelection.contributor($0.author) })
            .union(catalog.map { SourcesSelection.entry($0.id) })
    }

    /// DR-25 — "Sources · 7 connected", whatever is open. Sources v4 (review of #358): the position and the group
    /// ("2 of 7 · Saved by you") repeated what the list beside it already shows — the selected row and its group label
    /// (DR-38) — so the eyebrow stays the page's.
    static func eyebrow(groups: [SourceIntentGroups.Group], open: SourcesSelection?) -> String {
        let ordered = groups.flatMap(\.rows)
        return Eyebrow.text(Copy.sources, ordered.isEmpty ? "" : Copy.Lists.connected(ordered.count))
    }

    /// A contributor's share of entities written, from the strip's own segments (one scale, R-S6).
    static func share(of author: String, in segments: [ContributorShare.Segment]) -> Double? {
        segments.first { $0.author == author && !$0.isRemainder }?.fraction
    }

    /// Sources v3 — a click on Sources in the sidebar while Sources shows returns the page to its root, like a tab
    /// bar: the Reader and the detail close, whichever is open. Pure, so the rule is tested without a view.
    static func popsToRoot(detailOpen: Bool, readerOpen: Bool) -> Bool { detailOpen || readerOpen }
}

/// Sources v3 — a source row's one line, pure: what came from it in its own unit ("342 saved", "1,204 conversations")
/// and what it is doing ("Watching", "Captured by hook"); a failing source says its failure instead (the whole error
/// is the row's `.help` and the detail column's). No sparkline, no week-dots, no delta (owner 2026-10-19).
enum SourceListText {
    static func count(_ source: SourceOverview) -> String {
        switch source.intent {
        case .saved:
            // What the row's list lists, never its episodes: a capture is not a save (review of #347 — a watch-history
            // day once read "30 saved" over an empty list). The backend counts a channel-less row's saved pages.
            return source.items > 0 ? Copy.Lists.savedCount(source.items) : Copy.Lists.nothingSavedYet
        case .captured:
            guard let headline = source.headline else { return Copy.Lists.nothingYet }
            return Copy.Lists.headline(headline.count, noun: headline.noun)
        }
    }

    static func line(_ source: SourceOverview, liveness: SourceLiveness) -> String {
        liveness.tone.isAlarm ? liveness.verb : Eyebrow.text(count(source), liveness.verb)
    }
}

/// STATE 0 — the root (G245, ruling 78): the explore run (when one exists), the find and the kinds, then one capped
/// column of source cards, one shape for every source (`SourcesRootList`), and one quiet disclosure, *Statistics*, holding
/// who wrote the memory and the counts (the old `cicada.usageMode` key, DR-39). The page resolves the cards; this column
/// only lays them out, so the same view renders from fixtures.
struct SourcesOverviewColumn: View {
    let cards: [SourcesRoot.Card]
    let hasLoaded: Bool
    let onOpen: (SourcesSelection) -> Void
    var onSelectEntity: ((String) -> Void)?
    /// The field's words, the keys' cursor and the chosen kind: the page's own, so they outlive an opened source.
    var state: Binding<SourcesRoot.State> = .constant(SourcesRoot.State())
    /// ⏎ opens with no animation (DR-60); the pointer's `onOpen` keeps its drawer curve.
    var onOpenByKey: (SourcesSelection) -> Void = { _ in }
    /// A card's one button: Connect, or the fix it names.
    var onAct: (SourcesRoot.Card) -> Void = { _ in }
    var busy: Set<String> = []
    /// The clock the ages are read against; nil is the live one (a render pins it to its fixture).
    var clock: Date? = nil

    @Environment(UsageViewModel.self) private var usageVM
    @Environment(ExploreCache.self) private var exploreCache

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                    // G166 exploring — the run's one line of progress, Stop and Copy for an agent, while a run exists.
                    if exploreCache.showsCard { ExploreRunCard().frame(maxWidth: textCap, alignment: .leading) }
                    if !hasLoaded {
                        SourceCardSkeleton()
                    } else {
                        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
                            list(now: clock ?? context.date)
                        }
                    }
                    if !state.wrappedValue.searching { statistics.frame(maxWidth: textCap, alignment: .leading) }
                }
                .frame(maxWidth: SourcesRootLayout.columnWidth, alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.top, CicadaTheme.spacingXS)
                .padding(.bottom, CicadaTheme.scaled(72))
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: state.wrappedValue.cursor) { _, cursor in
                guard let cursor else { return }
                Instant.run { proxy.scrollTo(SourcesSelection.entry(cursor)) }
            }
        }
        // The same keys every list page has (DR-68): ↑/↓ walk the visible kind, ⏎ opens, Esc clears the find. None animates.
        .listKeys(move: { state.wrappedValue.walk($0, in: cards) }, enter: { enter() }, escape: { escapeFind() })
    }

    private func list(now: Date) -> some View {
        SourcesRootList(cards: cards, state: state, now: now, open: onOpen, openByKey: onOpenByKey, act: onAct, busy: busy)
    }

    /// ⏎ opens the lit card; with none lit it is nobody's key (the list is at rest).
    private func enter() -> Bool {
        guard let id = state.wrappedValue.lit(cards) else { return false }
        onOpenByKey(.entry(id))
        return true
    }

    private func escapeFind() {
        Instant.run { state.wrappedValue.clearFind() }
    }

    private var textCap: CGFloat { CicadaTheme.scaled(ColumnLayout.textMaxWidth) }

    /// R-DL23 (DR-39) — one quiet, remembered disclosure, on the same `cicada.usageMode` key, so an existing choice
    /// carries over. Sources v3 moves *Who wrote your memory* in here with the counts: both are statistics.
    private var statistics: some View {
        let isOpen = usageVM.mode == .advanced
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            DisclosureHeader(title: Copy.Lists.advancedStatistics, isOpen: isOpen, help: Copy.Lists.advancedHelp) {
                usageVM.mode = isOpen ? .minimal : .advanced
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            if isOpen {
                ContributorsStrip { onOpen(.contributor($0.author)) }
                AdvancedStatsView(onSelectEntity: onSelectEntity)
                    .padding(.horizontal, -CicadaTheme.spacingGutter)
            }
        }
    }
}

/// The two groups as labelled rows — one rendering for the root (wide) and the list beside an open source (triage,
/// titles). Liveness is passed in, so the list is a plain value view (the hosts read `BrowserWatcher`).
struct SourceGroupsList: View {
    let groups: [SourceIntentGroups.Group]
    let style: ColumnPlan.ListStyle
    var selection: SourcesSelection? = nil
    let liveness: (SourceOverview) -> SourceLiveness
    let open: (SourcesSelection) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: style == .titles || style == .hidden ? 0 : CicadaTheme.scaled(RowMetrics.twoLineGap)) {
            ForEach(Array(groups.enumerated()), id: \.element.intent) { index, group in
                SectionLabel(group.title)
                    .padding(.horizontal, CicadaTheme.scaled(10))
                    .padding(.top, index == 0 && style == .wide ? 0 : CicadaTheme.scaled(14))
                    .padding(.bottom, CicadaTheme.scaled(4))
                ForEach(group.rows) { row in
                    SourceListRow(source: row, liveness: liveness(row), style: style,
                                  selected: selection == .source(row.id)) { open(.source(row.id)) }
                        .id(SourcesSelection.source(row.id))
                }
            }
        }
    }
}

/// STATE 1 / 2 — the same cards as the narrow DR-34 rows beside the open source, in the root's order (needs you,
/// connected, not connected). Tabs and the find are the root's; the keys here walk what is drawn.
struct SourcesListColumn: View {
    let cards: [SourcesRoot.Card]
    let style: ColumnPlan.ListStyle
    let selection: SourcesSelection?
    let open: (SourcesSelection) -> Void
    let move: (Int) -> Void
    let escape: () -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                SourceCatalogList(cards: cards, style: style, selection: selection, open: open)
                    .padding(ListInsets.of(style))
            }
            .onChange(of: selection) { _, s in
                guard let s else { return }
                Instant.run { proxy.scrollTo(s) }
            }
        }
        .listKeys(move: move, enter: { false }, escape: escape)
    }
}

/// One source as a row: the bare mark (DR-52), the brand, and one line — what came from it and what it is doing
/// (`SourceListText`). Two lines at rest on the root and beside an open source; titles only when the column is narrow.
struct SourceListRow: View {
    let source: SourceOverview
    let liveness: SourceLiveness
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
        .listRowSurface(height: ListRowSurface.height(style, twoLineAtRest: true), selected: selected)
        .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: nil))
        .accessibilityAddTraits(selected ? .isSelected : [])
        .help(source.lastError ?? SourceListText.line(source, liveness: liveness))
    }

    private var name: some View {
        Text(SourceDisplayName.of(source))
            .font(CicadaTheme.font(size: 13, weight: selected || style == .wide ? .medium : .regular))
            .foregroundStyle(selected || style == .wide ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .lineLimit(1)
    }

    @ViewBuilder
    private var content: some View {
        switch style {
        case .triage, .wide:
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                OriginMark(origin: source.mark, size: CicadaTheme.scaled(14)).padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    name
                    Text(SourceListText.line(source, liveness: liveness))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(liveness.tone.isAlarm && !selected ? CicadaTheme.warning : metaColor)
                        .lineLimit(1)
                }
                // Sources v4 (owner 2026-10-19) — on the root, who and where it came from: the chats that fed Messages,
                // the sites a saved source's things came from; three faces, then "+N".
                if style == .wide && !source.faces.isEmpty {
                    Spacer(minLength: CicadaTheme.spacingSM)
                    // Centred on the two lines beside it (the row is top-aligned, so the stack is set down, never stretched).
                    SourceFaces(faces: source.faces, more: source.facesMore)
                        .padding(.top, CicadaTheme.scaled(6))
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
