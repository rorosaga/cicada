import SwiftUI

/// ROR-118 (owner, Sources round 1; round 5 after four rounds below the plain page) — the Sources root as kinds. Six
/// kinds of information, never vendors, one full-width column in a fixed order. Inside a kind the page does what the
/// plain tile page did and the ranked rows lost: every source is a visible, full-size mark with its name. What is
/// connected is a card (a ring on a fill, the status dot and when it last read, then what came in in the kind's own
/// way: titles, the week, marks, covers); what is not is a plain tile of the same family, logo and name, one tap to its
/// own page. No "Add X and N more" lines, no stacked marks: nothing is cut off and nothing is a count. A kind with
/// nothing connected is its tiles alone, so Events and Work read as finished. DR-9 (a ring, no shadow), DR-47 (labelled
/// groups), DR-48/DR-63 (hover is a fill), DR-52 (one logo tile), DR-60 (a key never animates).
enum SourceShelfLayout {
    /// The kinds the page draws: every one holding something, and every one that could still take something.
    static func shown(_ shelves: [SourceShelves.Shelf]) -> [SourceShelves.Shelf] {
        shelves.filter { !$0.connected.isEmpty || !$0.addable.isEmpty }
    }

    /// Tiles: 6 across on a wide page, the old page's grid; a connected card is two tiles wide.
    static let tileMinWidth: CGFloat = 180
    static let gap: CGFloat = 12
}

/// Equal cells in rows. Both grids on the page share one set of tile columns (as many as fit the minimum width, an even
/// number), and a card spans two of them, so a card and a tile never stagger; every cell in a row is as tall as the
/// tallest, so a card with two titles and a card with one still make a clean grid.
private struct EqualGridLayout: Layout {
    let minTile: CGFloat
    let gap: CGFloat
    /// How many tile columns a cell covers: 1 for a tile, 2 for a card.
    let span: Int

    private func tileColumns(_ width: CGFloat) -> Int { max(2, Int((width + gap) / (minTile + gap)) / 2 * 2) }

    private struct Grid { let columns: Int; let cell: CGFloat }
    private func grid(_ width: CGFloat) -> Grid {
        let n = tileColumns(width)
        let tile = (width - gap * CGFloat(n - 1)) / CGFloat(n)
        return Grid(columns: n / span, cell: tile * CGFloat(span) + gap * CGFloat(span - 1))
    }

    private func heights(_ subviews: Subviews, _ g: Grid) -> [CGFloat] {
        stride(from: 0, to: subviews.count, by: g.columns).map { start in
            subviews[start..<min(start + g.columns, subviews.count)]
                .map { $0.sizeThatFits(.init(width: g.cell, height: nil)).height }.max() ?? 0
        }
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? minTile * 2 + gap
        let rows = heights(subviews, grid(width))
        return CGSize(width: width, height: rows.reduce(0, +) + gap * CGFloat(max(0, rows.count - 1)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let g = grid(bounds.width)
        let rows = heights(subviews, g)
        var y = bounds.minY
        for (r, height) in rows.enumerated() {
            for c in 0..<g.columns where r * g.columns + c < subviews.count {
                subviews[r * g.columns + c].place(at: CGPoint(x: bounds.minX + CGFloat(c) * (g.cell + gap), y: y),
                                                  anchor: .topLeading, proposal: .init(width: g.cell, height: height))
            }
            y += height + gap
        }
    }
}

struct SourceShelvesView: View {
    let rows: [SourceCatalogRow]
    let open: (SourcesSelection) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            let shown = SourceShelfLayout.shown(SourceShelves.shelves(rows))
            let waiting = rows.filter(\.needsYou)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                if !waiting.isEmpty { SourceNeedsYou(rows: waiting, now: context.date, open: open) }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(28)) {
                    ForEach(shown, id: \.shelf) { shelf in
                        SourceShelfSection(shelf: shelf, now: context.date, open: open)
                    }
                }
            }
        }
    }
}

/// What waits on the person (a sign-in, a permission, an agent): one line each, amber, never a tile.
struct SourceNeedsYou: View {
    let rows: [SourceCatalogRow]
    let now: Date
    let open: (SourcesSelection) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Catalog.needsYou)
            VStack(spacing: 0) {
                ForEach(rows) { row in
                    SourceNeedsRow(row: row) { open(.entry(row.id)) }
                        .id(SourcesSelection.entry(row.id))
                }
            }
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        }
    }
}

private struct SourceNeedsRow: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                SourceLogoTile(origin: row.entry.origin)
                Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                StatusWord(word: row.word, tone: row.tone)
            }
            .padding(.horizontal, CicadaTheme.scaled(12))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.titleOnly + 8), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .help(row.help)
        .accessibilityLabel("\(row.entry.title), \(row.word)")
    }
}

/// One kind: its name, its connected sources as cards, then what else it takes as plain tiles. Both grids are equal
/// cells, so the eye reads a card as connected (a fill, a dot, a time) and a tile as available (a mark and a name).
struct SourceShelfSection: View {
    let shelf: SourceShelves.Shelf
    let now: Date
    let open: (SourcesSelection) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(shelf.shelf.title)
            if !shelf.connected.isEmpty {
                EqualGridLayout(minTile: CicadaTheme.scaled(SourceShelfLayout.tileMinWidth),
                                gap: CicadaTheme.scaled(SourceShelfLayout.gap), span: 2) {
                    ForEach(shelf.connected) { row in
                        SourceShelfRow(row: row, shelf: shelf.shelf, now: now) { open(.entry(row.id)) }
                            .id(SourcesSelection.entry(row.id))
                    }
                }
            }
            if !shelf.addable.isEmpty {
                EqualGridLayout(minTile: CicadaTheme.scaled(SourceShelfLayout.tileMinWidth),
                                gap: CicadaTheme.scaled(SourceShelfLayout.gap), span: 1) {
                    ForEach(shelf.addable) { row in
                        SourceAddTile(row: row) { open(.entry(row.id)) }.id(SourcesSelection.entry(row.id))
                    }
                }
            }
        }
    }
}

/// A source that is not connected: its own mark and its name in a plain tile, one tap to its page where it connects.
/// Calendar carries its one honest note (it reads Google too, when the person added Google to this Mac).
struct SourceAddTile: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                SourceLogoTile(origin: row.entry.origin)
                VStack(alignment: .leading, spacing: 1) {
                    Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if row.entry.id == "calendar-local" {
                        Text(Copy.Shelf.calendarNote).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(60), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .help(row.entry.title)
        .accessibilityLabel(row.entry.title)
    }
}

/// A connected source as a card: the logo tile, the name, the green dot and when it last read (the dot is what tells a
/// card from a tile at a glance, as on the plain page); what came in below, aligned to the name. The whole card opens it.
struct SourceShelfRow: View {
    let row: SourceCatalogRow
    let shelf: SourceShelf
    let now: Date
    let open: () -> Void

    @Environment(Store.self) private var store
    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @State private var hovering = false

    private var overview: SourceOverview? { SourceCatalog.overviewRow(for: row.entry, in: store.sourcesOverview.value ?? []) }
    /// The list this row's items come from: the overview row's own, else the entry's first channel.
    private var listId: String? { overview?.itemsListId ?? row.entry.channels.first }
    private var list: ChannelItemsList? { listId.flatMap { cache?.list($0) } }

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                HStack(spacing: CicadaTheme.scaled(12)) {
                    SourceLogoTile(origin: row.entry.origin)
                    Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    trailing
                }
                SourceShelfItems(shelf: shelf, items: list?.items ?? [], total: list?.all ?? list?.total ?? overview?.items,
                                 today: ISODay.today(now: now), counted: overview.flatMap(counted),
                                 mediaSymbol: Self.mediaSymbol(row.entry.id))
                    .padding(.leading, CicadaTheme.scaled(48))
            }
            .padding(CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityLabel("\(row.entry.title), \(row.word)")
        .task(id: listId) { if let listId { await cache?.refresh(listId) } }
    }

    /// The same place on every card: the dot and when it last read; a source that needs something says so in its tone.
    @ViewBuilder private var trailing: some View {
        if let line = SourceGrid.line(row, now: now) {
            StatusWord(word: line.word, tone: line.tone).monospacedDigit()
        }
    }
}

extension SourceShelfRow {
    /// The glyph on a cover that has no picture: the kind of thing this source holds.
    static func mediaSymbol(_ id: String) -> String {
        switch id {
        case "spotify": "music.note"
        case "youtube", "tiktok": "play.rectangle"
        case VoiceMemosReader.channel: "waveform"
        default: "book.closed"
        }
    }

    /// What a source with no list of titles still says: how many it holds, in its own unit (a harness's conversations).
    fileprivate func counted(_ overview: SourceOverview) -> String? {
        switch shelf {
        case .conversations where overview.conversations > 0: Copy.Shelf.conversationCount(overview.conversations)
        case .saved where overview.items > 0: Copy.Shelf.savedCount(overview.items)
        default: nil
        }
    }
}

/// The kind's own way of showing what came in: titles for conversations and documents; repositories with a code glyph
/// for work; the week for events; each save's title and the site it came from; covers for media. Pure data in, so it
/// draws the same for a test and for the page. No letter chips: a mark is a real icon or it is absent.
struct SourceShelfItems: View {
    let shelf: SourceShelf
    let items: [ChannelItem]
    let total: Int?
    let today: ISODay
    /// One quiet line when there are no titles to list.
    var counted: String? = nil
    /// The glyph on a media item with no cover.
    var mediaSymbol = "book.closed"

    var body: some View {
        if items.isEmpty, let counted {
            Text(counted).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
        } else { kind }
    }

    @ViewBuilder
    private var kind: some View {
        switch shelf {
        case .conversations, .documents: titles
        case .work: work
        case .events: SourceWeekStrip(items: items, today: today)
        case .saved: saved
        case .media: SourceCoverList(items: items, total: total, symbol: mediaSymbol)
        }
    }

    private func titleLine(_ item: ChannelItem) -> some View {
        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            .lineLimit(1).truncationMode(.tail)
    }

    @ViewBuilder
    private var titles: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                ForEach(items.prefix(2)) { titleLine($0) }
            }
        }
    }

    /// Work: what the tool holds, with a code glyph, and when it moved.
    @ViewBuilder
    private var work: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                ForEach(items.prefix(3)) { item in
                    HStack(spacing: CicadaTheme.scaled(8)) {
                        Image(systemName: "chevron.left.forwardslash.chevron.right").font(CicadaTheme.icon(.inline))
                            .foregroundStyle(CicadaTheme.textTertiary)
                        Text(item.title).font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary).lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if let day = SavedItemText.day(item, today: today) {
                            Text(day.text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).fixedSize()
                        }
                    }
                }
            }
        }
    }

    /// Saved: each title, and the site it came from at the end of the line.
    @ViewBuilder
    private var saved: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                ForEach(items.prefix(2)) { item in
                    HStack(spacing: CicadaTheme.scaled(8)) {
                        titleLine(item)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if let host = item.host {
                            Text(host).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                        }
                    }
                }
                if let total, total > 2 {
                    Text(Copy.Shelf.savedCount(total)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }
}

/// Events as the week they sit in: seven days, today filled, a dot under every day that holds something, and the next
/// two titles beneath. Calendar items carry an absolute `YYYY-MM-DD` day (`ChannelItem.day`); nothing is guessed.
struct SourceWeekStrip: View {
    let items: [ChannelItem]
    let today: ISODay

    /// Monday-first week containing today, as ISODays.
    static func week(containing today: ISODay, calendar: Calendar = .autoupdatingCurrent) -> [ISODay] {
        let weekday = ((today.ordinal + 3) % 7 + 7) % 7   // 1970-01-01 was a Thursday: 0 = Monday
        let first = today.adding(-weekday)
        return (0..<7).map { first.adding($0) }
    }

    /// The days of the week that hold an item, and the next items from today on (else the latest).
    static func busy(_ items: [ChannelItem], in week: [ISODay]) -> Set<ISODay> {
        Set(items.compactMap { ISODay($0.day) }.filter(week.contains))
    }

    static func upcoming(_ items: [ChannelItem], today: ISODay, limit: Int = 2) -> [ChannelItem] {
        let dated = items.compactMap { item in ISODay(item.day).map { (item, $0) } }
        let ahead = dated.filter { $0.1 >= today }.sorted { $0.1 < $1.1 }.map(\.0)
        return Array((ahead.isEmpty ? dated.map(\.0) : ahead).prefix(limit))
    }

    private static let letters = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        let week = Self.week(containing: today)
        let busy = Self.busy(items, in: week)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: 0) {
                ForEach(Array(week.enumerated()), id: \.offset) { index, day in
                    let isToday = day == today
                    VStack(spacing: CicadaTheme.scaled(4)) {
                        Text(Self.letters[index]).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        Text(String(day.civil.day)).font(CicadaTheme.bodyFont).monospacedDigit()
                            .foregroundStyle(isToday ? CicadaTheme.onAccent : CicadaTheme.textPrimary)
                            .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                            .background(Circle().fill(isToday ? CicadaTheme.accent : Color.clear))
                        Circle().fill(busy.contains(day) ? CicadaTheme.info : Color.clear)
                            .frame(width: CicadaTheme.scaled(5), height: CicadaTheme.scaled(5))
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            ForEach(Self.upcoming(items, today: today)) { item in
                HStack(spacing: CicadaTheme.scaled(8)) {
                    Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let day = SavedItemText.day(item, today: today) {
                        Text(day.text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).fixedSize()
                    }
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Media as what it looks like: each item as a small cover (a book's, a video's still, else a quiet tile with the kind's
/// own glyph) beside its title, never a letter standing for a site.
struct SourceCoverList: View {
    let items: [ChannelItem]
    let total: Int?
    let symbol: String

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                ForEach(items.prefix(3)) { item in
                    HStack(spacing: CicadaTheme.scaled(10)) {
                        cover(item)
                        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(1).truncationMode(.tail)
                    }
                }
                if let total, total > 3 {
                    Text(Copy.Shelf.itemCount(total)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }

    @ViewBuilder
    private func cover(_ item: ChannelItem) -> some View {
        if let still = SavedItemText.stillPath(item) {
            VideoStill(path: still)
        } else if item.book == true, item.cover != nil {
            BookCoverThumb(path: item.cover, points: 34, reservesSlot: true)
        } else {
            let shape = CicadaTheme.shape(CicadaTheme.scaled(4))
            ZStack {
                shape.fill(CicadaTheme.surfaceElevated)
                Image(systemName: symbol).font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .frame(width: CicadaTheme.scaled(23), height: CicadaTheme.scaled(34))
            .ringed(in: shape)
            .accessibilityHidden(true)
        }
    }
}
