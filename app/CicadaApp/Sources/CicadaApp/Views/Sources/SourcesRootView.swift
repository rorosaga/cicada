import SwiftUI

// G245 (ruling 78, plan 3.1) — the Sources root: one column of source cards, one shape for every source. DR-37 (an item
// with words and a source is its own card), the 2026-11-23 soft-card line (`softCardRow`, the Sleep queue's look),
// DR-45 (tabs with counts), DR-46 (the in-page find), DR-52 (a real mark), DR-60/61 (a key never animates; a duration
// lives in `CicadaMotion`), DR-81 (a section with nothing in it is not drawn).

/// The root's one column: capped like the Sleep page, left-aligned under the header, which is capped to the same edge so
/// its button sits over the cards' right edge, not at the window's.
enum SourcesRootLayout {
    static var columnWidth: CGFloat { CicadaTheme.scaled(SleepLayout.pageWidth) }
    static func headerWidth(gutter: CGFloat) -> CGFloat { columnWidth + 2 * gutter }
}

/// Where each root card's top sits in the root's scroll view (a viewport-relative y), so the page can keep its place while
/// a source is open and the root is gone (found in the real app: closing a source returned to the top).
struct SourceCardTops: PreferenceKey {
    static var defaultValue: [String: CGFloat] = [:]
    static func reduce(value: inout [String: CGFloat], nextValue: () -> [String: CGFloat]) {
        value.merge(nextValue()) { $1 }
    }
}

enum SourcesRootScroll {
    static let space = "sourcesRootScroll"

    /// The card to keep the place by: the first one whole in view below the top edge (a restore puts its top at the edge,
    /// so a card cut by the edge would move the page by most of its height). Nil while no card has scrolled past the edge
    /// (the controls above the cards are still in view, so there is nothing to keep).
    static func topCard(_ tops: [String: CGFloat]) -> String? {
        guard tops.values.contains(where: { $0 < 0 }) else { return nil }
        let whole = tops.filter { $0.value >= -1 }
        if let first = whole.min(by: { $0.value < $1.value }) { return first.key }
        return tops.max { $0.value < $1.value }?.key
    }
}

/// One source as a card. Line one: the mark, the name, and at the trailing edge its state and when it last read. Line two,
/// quiet: the streams it reads ("Bookmarks 214 · Likes 1,032 · 3 folders"), or, for a source not connected, what it
/// could read, in the tertiary ink. The whole card opens the source; the one button on it (Connect, or the fix a
/// needs-you card names) is outside that tap target, so a card never nests a button in a button.
///
/// The card is `softCardRow(ground: .page)`: `sourceCardChrome` is the chrome of a card that holds cards, and this one
/// holds none (critic app8).
struct SourceRootCard: View {
    let card: SourcesRoot.Card
    /// The card the arrows or the find are on: the selected-row fill, never the accent (DR-48).
    var highlighted = false
    let now: Date
    let open: () -> Void
    /// Connect, or the fix; the same closure, because a card carries only one of them.
    let act: () -> Void
    /// The card's button is working (a check ran from it, a connect is writing).
    var busy = false
    /// A check this card's streams just ended in (`SourceStreamCheckModel.cardWord`): shown for a while in place of the
    /// state, so the root says what each connection answered, not only that a check ran.
    var checked: (word: StreamWord, how: StreamHow)?
    @Environment(SourceStreamCheckModel.self) private var checkModel: SourceStreamCheckModel?

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            Button(action: open) {
                HStack(alignment: .center, spacing: CicadaTheme.scaled(14)) {
                    SourceLogoTile(origin: card.row.entry.origin)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                        Text(card.row.entry.title)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        if let line = card.line {
                            Text(line.text())
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(line.ink == .on ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    trailing
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(accessibilityLabel)
            .accessibilityAddTraits(highlighted ? .isSelected : [])
            .help(card.row.help)
            button
        }
        // One height for every card, a one-line card (nothing specific to say under its name) centred in it like its
        // two-line neighbours.
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.sourceCardContent))
        .softCardRow(ground: .page, selected: highlighted)
        .id(SourcesSelection.entry(card.id))
        .background(GeometryReader { geo in
            Color.clear.preference(key: SourceCardTops.self,
                                   value: [card.id: geo.frame(in: .named(SourcesRootScroll.space)).minY])
        })
    }

    /// The state and, once it has read, when: the word in its colour, the age beside it in the tertiary ink.
    @ViewBuilder private var trailing: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if card.showsLastRead, let read = card.lastRead {
                Text(SourceCatalog.ago(read, now: now))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            if let word = shownCheck {
                StatusWord(word: word.word.text, tone: word.word.tone(how: word.how))
            } else if let trailing = card.trailingWord {
                StatusWord(word: trailing.word, tone: trailing.tone)
            }
        }
    }

    private var shownCheck: (word: StreamWord, how: StreamHow)? {
        checked ?? checkModel.flatMap {
            SourceStreamCheckModel.cardWord(streams: card.streams, results: $0.results, now: now)
        }
    }

    @ViewBuilder private var button: some View {
        if let fix = card.fix {
            NeutralButton(title: fix.title, size: .compact, isDisabled: busy, action: act)
        } else if card.connectable {
            NeutralButton(title: Copy.Streams.connect, size: .compact, isDisabled: busy,
                          help: Copy.Streams.connectHelp(card.row.entry.title), action: act)
        }
    }

    private var accessibilityLabel: String {
        [card.row.entry.title, shownCheck?.word.text ?? card.trailingWord?.word, card.line?.text()].compactMap { $0 }.joined(separator: ", ")
    }
}

/// The root's cards, tabs and find, as one value-driven view: the page hands it the cards it resolved, so a render test
/// draws the same view from fixtures. Nothing here reads the network or a model.
struct SourcesRootList: View {
    let cards: [SourcesRoot.Card]
    @Binding var state: SourcesRoot.State
    let now: Date
    let open: (SourcesSelection) -> Void
    /// ⏎ in the field or on a card: an open that never animates (DR-60).
    let openByKey: (SourcesSelection) -> Void
    let act: (SourcesRoot.Card) -> Void
    var busy: Set<String> = []

    var body: some View {
        let shown = state.visible(cards)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            controls
            if shown.isEmpty {
                EmptyStateView(title: Copy.Catalog.noMatch(state.text.trimmingCharacters(in: .whitespacesAndNewlines)),
                               message: "", showsDropHint: false)
            } else {
                column(shown)
            }
        }
    }

    // MARK: The find and the kinds

    /// Tabs left, the find on the right of the same row while they fit; stacked when the column is too narrow for both.
    private var controls: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingLG) {
                tabs
                Spacer(minLength: CicadaTheme.spacingSM)
                field
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                field
                tabs
            }
        }
    }

    private var field: some View {
        CicadaSearchField(text: Binding(get: { state.text }, set: { state.typed($0) }),
                          prompt: Copy.Catalog.searchPrompt,
                          onSubmit: { if let id = state.lit(cards) { openByKey(.entry(id)) } },
                          onMove: { state.walk($0, in: cards) })
            .frame(width: CicadaTheme.scaled(SourceGrid.searchMaxWidth))
    }

    private var tabs: some View {
        let all = SourcesRoot.tabs(cards).map { tab in TextTab<SourceShelf>(id: tab.shelf, label: tab.label, count: tab.count) }
        let selection = Binding<SourceShelf?>(get: { SourcesRoot.effectiveTab(state.tab, cards: cards) }, set: { chosen in
            // A tab switch is instant (DR-61), and it starts the walk again from the top.
            Instant.run { state.tab = chosen; state.cursor = nil }
        })
        return ViewThatFits(in: .horizontal) {
            TextTabs(tabs: all, selection: selection, large: true)
            OverflowTextTabs(tabs: all, selection: selection)
        }
        .accessibilityLabel(Copy.Streams.kindsLabel)
    }

    // MARK: Cards

    private func column(_ shown: [SourcesRoot.Card]) -> some View {
        let groups = SourcesRoot.sections(shown, searching: state.searching)
        let lit = state.lit(cards)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
            ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                VStack(alignment: .leading, spacing: CicadaTheme.cardGap) {
                    if let label = group.label { SectionLabel(label).padding(.leading, CicadaTheme.spacingXS) }
                    ForEach(group.cards) { card in
                        SourceRootCard(card: card, highlighted: card.id == lit, now: now,
                                   open: { open(.entry(card.id)) }, act: { act(card) },
                                   busy: busy.contains(card.id))
                    }
                }
            }
        }
    }
}

/// Placeholder cards at the real size, no motion: a page that knows its shape draws it (never blank, DR-43).
struct SourceCardSkeleton: View {
    var body: some View {
        VStack(spacing: CicadaTheme.cardGap) {
            ForEach(0..<6, id: \.self) { _ in
                CicadaTheme.shape(CicadaTheme.radiusLarge)
                    .fill(CicadaTheme.bgSelected)
                    .frame(height: CicadaTheme.scaled(RowMetrics.sourceTile + 4))
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.Streams.readingSources)
    }
}
