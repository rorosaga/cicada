import SwiftUI

/// ROR-118 (owner, Sources round 1; round 3 after the judges) — the Sources root as kinds. Six kinds of information,
/// never vendors. Each draws its connected sources as plain rows on the page's own ground (no card, no ring: a ring
/// per source made twenty boxes), one logo tile size throughout, and shows what came in its own way (titles, the week,
/// marks, covers). What is not connected is never a mark on this page: a kind with nothing in it is one dashed line
/// naming what it takes, and the "+" beside every kind's name opens the add overlay on it. So a row is connected and a
/// dashed line is not, at a glance. DR-9 (a ring, no shadow), DR-47 (labelled groups), DR-48/DR-63 (hover is a fill),
/// DR-52 (one logo tile), DR-60 (a key never animates).
enum SourceShelfLayout {
    /// Two columns on a wide page, one fixed place per kind, so a kind never moves when a source joins it; on a narrow
    /// page the same six stack in `SourceShelf.allCases` order.
    static func column(_ shelf: SourceShelf) -> Int {
        switch shelf {
        case .conversations, .events, .work: 0
        case .documents, .saved, .media: 1
        }
    }

    /// The kinds the page draws: every one holding something, and every one that could still take something.
    static func shown(_ shelves: [SourceShelves.Shelf]) -> [SourceShelves.Shelf] {
        shelves.filter { !$0.connected.isEmpty || !$0.addable.isEmpty }
    }

    static let columnMinWidth: CGFloat = 340
    static let columnGap: CGFloat = 56
}

private struct ShelfColumnKey: LayoutValueKey { static let defaultValue = 0 }

/// The kinds in two columns when the page is wide enough, else in one, in the order given.
private struct ShelfColumnsLayout: Layout {
    let minColumn: CGFloat
    let gap: CGFloat
    let rowGap: CGFloat

    private func count(_ width: CGFloat) -> Int { width >= minColumn * 2 + gap ? 2 : 1 }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? minColumn * 2 + gap
        let n = count(width)
        let colWidth = (width - gap * CGFloat(n - 1)) / CGFloat(n)
        var heights = [CGFloat](repeating: 0, count: n)
        for sub in subviews {
            let c = n == 1 ? 0 : sub[ShelfColumnKey.self]
            heights[c] += (heights[c] > 0 ? rowGap : 0) + sub.sizeThatFits(.init(width: colWidth, height: nil)).height
        }
        return CGSize(width: width, height: heights.max() ?? 0)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let n = count(bounds.width)
        let colWidth = (bounds.width - gap * CGFloat(n - 1)) / CGFloat(n)
        var y = [CGFloat](repeating: bounds.minY, count: n)
        for sub in subviews {
            let c = n == 1 ? 0 : sub[ShelfColumnKey.self]
            let size = sub.sizeThatFits(.init(width: colWidth, height: nil))
            sub.place(at: CGPoint(x: bounds.minX + CGFloat(c) * (colWidth + gap), y: y[c]), anchor: .topLeading,
                      proposal: .init(width: colWidth, height: size.height))
            y[c] += size.height + rowGap
        }
    }
}

struct SourceShelvesView: View {
    let rows: [SourceCatalogRow]
    let open: (SourcesSelection) -> Void
    let add: (SourceShelf?) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            let shown = SourceShelfLayout.shown(SourceShelves.shelves(rows))
            let waiting = rows.filter(\.needsYou)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                if !waiting.isEmpty { SourceNeedsYou(rows: waiting, now: context.date, open: open) }
                ShelfColumnsLayout(minColumn: CicadaTheme.scaled(SourceShelfLayout.columnMinWidth),
                                   gap: CicadaTheme.scaled(SourceShelfLayout.columnGap), rowGap: CicadaTheme.scaled(36)) {
                    ForEach(shown, id: \.shelf) { shelf in
                        SourceShelfSection(shelf: shelf, now: context.date, open: open, add: add)
                            .layoutValue(key: ShelfColumnKey.self, value: SourceShelfLayout.column(shelf.shelf))
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

/// One kind: its name with a "+" that opens the add overlay on it, then its connected sources as rows, or, with none,
/// one dashed line naming what it takes.
struct SourceShelfSection: View {
    let shelf: SourceShelves.Shelf
    let now: Date
    let open: (SourcesSelection) -> Void
    let add: (SourceShelf?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack {
                SectionLabel(shelf.shelf.title)
                Spacer(minLength: 0)
                if !shelf.addable.isEmpty {
                    Button { add(shelf.shelf) } label: {
                        Image(systemName: "plus").font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)
                            .frame(width: CicadaTheme.scaled(24), height: CicadaTheme.scaled(24))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.cicadaPlain)
                    .help(Copy.Shelf.add(shelf.addNames))
                    .accessibilityLabel(Copy.Shelf.add(shelf.addNames))
                }
            }
            if shelf.connected.isEmpty {
                SourceEmptyLine(shelf: shelf) { add(shelf.shelf) }
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                    ForEach(shelf.connected) { row in
                        SourceShelfRow(row: row, shelf: shelf.shelf, now: now) { open(.entry(row.id)) }
                            .id(SourcesSelection.entry(row.id))
                    }
                }
            }
        }
    }
}

/// A kind with nothing connected: one dashed line with the kind's glyph and what it takes, by name; a tap opens the add
/// overlay on the kind. Dashed means not here yet; a source that is here is always a row.
struct SourceEmptyLine: View {
    let shelf: SourceShelves.Shelf
    let add: () -> Void
    @State private var hovering = false

    private var shape: some InsettableShape { CicadaTheme.shape(CicadaTheme.cornerRadius) }

    var body: some View {
        Button(action: add) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                Image(systemName: shelf.shelf.symbol).font(CicadaTheme.icon(.list)).foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(36))
                Text(shelf.addNames.joined(separator: ", ")).font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(52), alignment: .leading)
            .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .background(shape.strokeBorder(CicadaTheme.border, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
        .accessibilityLabel(Copy.Shelf.add(shelf.addNames))
    }
}

/// A connected source: the logo tile, the name, when it last read; what came in below, aligned to the name. The whole
/// row opens the source; nothing inside it is a second control.
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
                    if let line = SourceGrid.line(row, now: now) {
                        StatusWord(word: line.word, tone: line.tone).monospacedDigit()
                    }
                }
                SourceShelfItems(shelf: shelf, items: list?.items ?? [], total: list?.all ?? list?.total ?? overview?.items,
                                 today: ISODay.today(now: now), counted: overview.flatMap(counted))
                    .padding(.leading, CicadaTheme.scaled(48))
            }
            .padding(CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .accessibilityLabel("\(row.entry.title), \(row.word)")
        .task(id: listId) { if let listId { await cache?.refresh(listId) } }
    }
}

extension SourceShelfRow {
    /// What a source with no list of titles still says: how many it holds, in its own unit (a harness's conversations).
    fileprivate func counted(_ overview: SourceOverview) -> String? {
        switch shelf {
        case .conversations where overview.conversations > 0: Copy.Shelf.conversationCount(overview.conversations)
        case .saved where overview.items > 0: Copy.Shelf.savedCount(overview.items)
        default: nil
        }
    }
}

/// The kind's own way of showing what came in, quietly: two titles in the secondary ink, no dates; the week for events;
/// marks for saved; covers for media. Pure data in, so it draws the same for a test and for the page.
struct SourceShelfItems: View {
    let shelf: SourceShelf
    let items: [ChannelItem]
    let total: Int?
    let today: ISODay
    /// One quiet line when there are no titles to list.
    var counted: String? = nil

    var body: some View {
        if items.isEmpty, let counted {
            Text(counted).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        } else { kind }
    }

    @ViewBuilder
    private var kind: some View {
        switch shelf {
        case .conversations, .documents, .work: titles
        case .events: SourceWeekStrip(items: items, today: today)
        case .saved: saved
        case .media: SourceCoverStrip(items: items, total: total)
        }
    }

    private func titleLine(_ item: ChannelItem) -> some View {
        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            .lineLimit(1).truncationMode(.tail)
    }

    @ViewBuilder
    private var titles: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                ForEach(items.prefix(2)) { titleLine($0) }
            }
        }
    }

    @ViewBuilder
    private var saved: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                ForEach(items.prefix(2)) { item in
                    HStack(spacing: CicadaTheme.scaled(8)) {
                        SavedLinkMark(mark: SavedItemText.mark(item), size: .row)
                        titleLine(item)
                    }
                }
                if let total, total > 2 {
                    Text(Copy.Shelf.savedCount(total)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
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

    private static let letters = ["M", "T", "W", "T", "F", "S", "S"]

    var body: some View {
        let week = Self.week(containing: today)
        let busy = Self.busy(items, in: week)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: 0) {
                ForEach(Array(week.enumerated()), id: \.offset) { index, day in
                    let isToday = day == today
                    VStack(spacing: CicadaTheme.scaled(4)) {
                        Text(Self.letters[index]).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        Text(String(day.civil.day)).font(CicadaTheme.metaFont).monospacedDigit()
                            .foregroundStyle(isToday ? CicadaTheme.onAccent : CicadaTheme.textPrimary)
                            .frame(width: CicadaTheme.scaled(26), height: CicadaTheme.scaled(26))
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
                        Text(day.text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).fixedSize()
                    }
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Media as what it looks like: a book's cover, a video's still, else the site's mark, in a row, with the count.
struct SourceCoverStrip: View {
    let items: [ChannelItem]
    let total: Int?

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                HStack(alignment: .top, spacing: CicadaTheme.scaled(8)) {
                    ForEach(items.prefix(5)) { item in cover(item) }
                    Spacer(minLength: 0)
                }
                if let total { Text(Copy.Shelf.itemCount(total)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary) }
            }
        }
    }

    @ViewBuilder
    private func cover(_ item: ChannelItem) -> some View {
        if let still = SavedItemText.stillPath(item) {
            VideoStill(path: still)
        } else if item.book == true {
            BookCoverThumb(path: item.cover, points: 48, reservesSlot: false)
        } else {
            SavedLinkMark(mark: SavedItemText.mark(item), size: .row)
        }
    }
}
