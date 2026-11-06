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

/// One kind: its name, its connected sources as rows, and one line that names what else it takes ("Add Apple Notes,
/// Contacts") with those apps' own marks. A kind with nothing connected is just that line, never a box: a row is
/// connected, a plus line is not.
struct SourceShelfSection: View {
    let shelf: SourceShelves.Shelf
    let now: Date
    let open: (SourcesSelection) -> Void
    let add: (SourceShelf?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(shelf.shelf.title)
            if !shelf.connected.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                    ForEach(shelf.connected) { row in
                        SourceShelfRow(row: row, shelf: shelf.shelf, now: now) { open(.entry(row.id)) }
                            .id(SourcesSelection.entry(row.id))
                    }
                }
            }
            if !shelf.addable.isEmpty { SourceAddLine(shelf: shelf) { add(shelf.shelf) } }
        }
    }
}

/// The one way to add to a kind: a plus, the names of what it takes, and their marks. A tap opens the add overlay on
/// the kind. Same height and rhythm as a source row, so a kind with nothing in it still reads as finished.
struct SourceAddLine: View {
    let shelf: SourceShelves.Shelf
    let add: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: add) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                Image(systemName: "plus").font(CicadaTheme.icon(.list)).foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(36))
                Text(Copy.Shelf.add(shelf.addNames, more: shelf.addMore)).font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                HStack(spacing: CicadaTheme.scaled(-8)) {
                    ForEach(Array(shelf.addable.prefix(3).enumerated()), id: \.element.id) { index, row in
                        SourceLogoTile(origin: row.entry.origin, size: .dense).zIndex(Double(-index))
                    }
                }
            }
            .padding(CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(52), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .help(Copy.Shelf.add(shelf.addable.map(\.entry.title), more: 0))
        .accessibilityLabel(Copy.Shelf.add(shelf.addNames, more: shelf.addMore))
    }
}

/// A connected source: the logo tile, the name, when it last read (time only: every row on this page is connected, so a
/// dot or the word "Connected" said nothing); what came in below, aligned to the name. The whole row opens the source.
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
            .padding(CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .accessibilityLabel("\(row.entry.title), \(row.word)")
        .task(id: listId) { if let listId { await cache?.refresh(listId) } }
    }

    /// The same place on every row: when it last read. Only a source that needs something says more, with its dot.
    @ViewBuilder private var trailing: some View {
        if let line = SourceGrid.line(row, now: now) {
            if line.tone == .on {
                if line.word != row.status.word {
                    Text(line.word).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        .monospacedDigit().lineLimit(1)
                }
            } else {
                StatusWord(word: line.word, tone: line.tone).monospacedDigit()
            }
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
            Text(counted).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
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
        Text(item.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
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
