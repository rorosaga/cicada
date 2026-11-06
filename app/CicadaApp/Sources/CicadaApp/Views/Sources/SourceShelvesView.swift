import SwiftUI

/// ROR-118 (owner, Sources round 1) — the Sources root as shelves. Six kinds of information, never vendors; each shelf
/// draws its connected sources in its own way (conversations as a list of titles, events as the week, saved as marks
/// and titles, media as covers and stills), and ends in one line that adds another. What waits on the person leads,
/// as words, not as a section of tiles. DR-9 (a ring, no shadow), DR-47 (labelled groups), DR-48/DR-63 (hover is a
/// fill), DR-52 (one logo tile), DR-60 (a key never animates).
enum SourceShelfLayout {
    /// Two columns when the page is wide enough, the shelves dealt to the shorter column in turn, so neither runs long.
    static func columns(_ shelves: [SourceShelves.Shelf]) -> (left: [SourceShelves.Shelf], right: [SourceShelves.Shelf]) {
        var left: [SourceShelves.Shelf] = [], right: [SourceShelves.Shelf] = []
        var leftHeight = 0, rightHeight = 0
        for shelf in shelves {
            let height = weight(shelf)
            if leftHeight <= rightHeight { left.append(shelf); leftHeight += height } else { right.append(shelf); rightHeight += height }
        }
        return (left, right)
    }

    /// A shelf's height in card units: its heading and add line, and each card (a list shelf's card is three rows).
    static func weight(_ shelf: SourceShelves.Shelf) -> Int { 2 + shelf.connected.count * 3 }

    static let twoColumnMinWidth: CGFloat = 820
}

struct SourceShelvesView: View {
    let rows: [SourceCatalogRow]
    let open: (SourcesSelection) -> Void
    let add: (SourceShelf?) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            let shelves = SourceShelves.shelves(rows)
            let waiting = rows.filter(\.needsYou)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                if !waiting.isEmpty { SourceNeedsYou(rows: waiting, now: context.date, open: open) }
                ViewThatFits(in: .horizontal) {
                    let split = SourceShelfLayout.columns(shelves)
                    HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                        column(split.left, now: context.date)
                        column(split.right, now: context.date)
                    }
                    .frame(minWidth: CicadaTheme.scaled(SourceShelfLayout.twoColumnMinWidth))
                    column(shelves, now: context.date)
                }
            }
        }
    }

    private func column(_ shelves: [SourceShelves.Shelf], now: Date) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
            ForEach(shelves, id: \.shelf) { shelf in
                SourceShelfSection(shelf: shelf, now: now, open: open, add: add)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
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
                SourceLogoTile(origin: row.entry.origin, size: .dense)
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

/// One kind: its heading, the connected sources it holds (each drawn its own way), and the line that adds another.
struct SourceShelfSection: View {
    let shelf: SourceShelves.Shelf
    let now: Date
    let open: (SourcesSelection) -> Void
    let add: (SourceShelf?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(shelf.shelf.title, count: shelf.connected.isEmpty ? nil : shelf.connected.count)
            ForEach(shelf.connected) { row in
                SourceShelfCard(row: row, shelf: shelf.shelf, now: now) { open(.entry(row.id)) }
                    .id(SourcesSelection.entry(row.id))
            }
            if !shelf.addNames.isEmpty {
                SourceAddLine(names: shelf.addNames, quiet: shelf.connected.isEmpty) { add(shelf.shelf) }
            }
        }
    }
}

/// "+ Add Notion, Folders": opens the overlay on this kind. On an empty shelf it is the whole shelf, so it is the one
/// ringed line; under sources it is a quiet text row.
struct SourceAddLine: View {
    let names: [String]
    var quiet = true
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(8)) {
                Image(systemName: "plus").font(CicadaTheme.icon(.inline))
                Text(Copy.Shelf.add(names)).font(CicadaTheme.metaFont).lineLimit(1)
                Spacer(minLength: 0)
            }
            .foregroundStyle(hovering ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.scaled(quiet ? 12 : 4))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.titleOnly), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.Shelf.add(names))
    }
}

/// A connected source on its shelf: the logo tile, the name and when it last read, then what came in, drawn for the
/// kind. The whole card opens the source; nothing inside it is a second control.
struct SourceShelfCard: View {
    let row: SourceCatalogRow
    let shelf: SourceShelf
    let now: Date
    let open: () -> Void

    @Environment(Store.self) private var store
    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @State private var hovering = false

    private var shape: some InsettableShape { CicadaTheme.shape(CicadaTheme.cornerRadius) }
    private var overview: SourceOverview? { SourceCatalog.overviewRow(for: row.entry, in: store.sourcesOverview.value ?? []) }
    /// The list this card's items come from: the overview row's own, else the entry's first channel.
    private var listId: String? { overview?.itemsListId ?? row.entry.channels.first }
    private var list: ChannelItemsList? { listId.flatMap { cache?.list($0) } }

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.scaled(12)) {
                    SourceLogoTile(origin: row.entry.origin)
                    Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let line = SourceGrid.line(row, now: now) {
                        StatusWord(word: line.word, tone: line.tone).monospacedDigit()
                    }
                }
                SourceShelfItems(shelf: shelf, items: list?.items ?? [], total: list?.all ?? list?.total ?? overview?.items,
                                 today: ISODay.today(now: now))
            }
            .padding(CicadaTheme.scaled(12))
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: shape)
        .accessibilityLabel("\(row.entry.title), \(row.word)")
        .task(id: listId) { if let listId { await cache?.refresh(listId) } }
    }
}

/// The kind's own way of showing what came in. Pure data in, so it draws the same for a test and for the page.
struct SourceShelfItems: View {
    let shelf: SourceShelf
    let items: [ChannelItem]
    let total: Int?
    let today: ISODay

    var body: some View {
        switch shelf {
        case .conversations: titles(glyph: nil, limit: 3)
        case .documents: titles(glyph: "doc.text", limit: 3)
        case .work: titles(glyph: "chevron.left.forwardslash.chevron.right", limit: 3)
        case .events: SourceWeekStrip(items: items, today: today)
        case .saved: saved
        case .media: SourceCoverStrip(items: items, total: total)
        }
    }

    @ViewBuilder
    private func titles(glyph: String?, limit: Int) -> some View {
        if !items.isEmpty {
            VStack(spacing: 0) {
                ForEach(items.prefix(limit)) { item in
                    HStack(spacing: CicadaTheme.scaled(8)) {
                        if let glyph {
                            Image(systemName: glyph).font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)
                        }
                        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if let day = SavedItemText.day(item, today: today) {
                            Text(day.text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                .monospacedDigit().lineLimit(1).fixedSize()
                        }
                    }
                    .frame(minHeight: CicadaTheme.scaled(30))
                }
            }
        }
    }

    @ViewBuilder
    private var saved: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(items.prefix(3)) { item in
                    HStack(spacing: CicadaTheme.scaled(8)) {
                        SavedLinkMark(mark: SavedItemText.mark(item), size: .inline)
                        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: 0)
                    }
                    .frame(minHeight: CicadaTheme.scaled(30))
                }
                if let total, total > 3 {
                    Text(Copy.Shelf.savedCount(total)).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary).padding(.top, CicadaTheme.scaled(2))
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
            BookCoverThumb(path: item.cover, points: 64, reservesSlot: false)
        } else {
            SavedLinkMark(mark: SavedItemText.mark(item), size: .row)
        }
    }
}
