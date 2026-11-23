import Foundation

// G245 (plan 3.1) — the Sources root as a column of source cards, pure. One card shape for every source: the real mark
// and name, the state and when it last read, and one quiet line of streams ("Bookmarks 214 · Likes 1,032 · 3 folders",
// or, for a source not connected, what it can read). This file decides the order, the tabs, the find and the keys; the
// view draws it.
//
// **One truth:** the card's state word and tone, the eyebrow's "N connected" and the needs-you split come from
// `SourceCatalogRow` exactly as before (`SourceCatalog.resolved`, the 2026-11-06 sources-truth rules). Streams add only
// the per-stream names, counts and health.

enum SourcesRoot {
    /// Where a card sits: what needs the person, then what is connected, then the rest.
    enum Group: Int, Comparable, Sendable {
        case needsYou, connected, notConnected
        static func < (a: Group, b: Group) -> Bool { a.rawValue < b.rawValue }
    }

    /// The card's second line.
    struct StreamsLine: Equatable, Sendable {
        struct Part: Equatable, Sendable {
            let label: String
            /// nil for a stream with nothing counted (a source's own list, a stream whose count the backend does not know).
            let count: Int?
        }

        /// `on`: the streams that are on, with their counts, in the ink of the page. `available`: what a source not
        /// connected could read, names only, in the tertiary ink.
        enum Ink: Equatable, Sendable { case on, available }

        let ink: Ink
        let parts: [Part]
        let folders: Int

        /// "Bookmarks 214 · Likes 1,032 · 3 folders". Counts in the reader's locale (R-S18).
        func text(locale: Locale = .autoupdatingCurrent) -> String {
            var out = parts.map { part in
                part.count.map { "\(part.label) \(UsageFormat.count($0, locale: locale))" } ?? part.label
            }
            if folders > 0 { out.append(Copy.Streams.folders(folders)) }
            return out.joined(separator: " · ")
        }
    }

    struct Card: Identifiable, Equatable {
        let row: SourceCatalogRow
        let group: Group
        let streams: [ResolvedStream]
        let line: StreamsLine?
        /// The newest read of the source: its channels' last sync or any stream's last read.
        let lastRead: Date?

        var id: String { row.id }
        var shelf: SourceShelf { row.entry.shelf }
        /// The state word and tone of the card: the catalogue's, unchanged.
        var word: String { row.word }
        var tone: StatusWord.Tone { row.tone }
        /// Whether the card says when it last read (a source that is not connected says nothing of the kind).
        var showsLastRead: Bool { group != .notConnected && lastRead != nil }
    }

    // MARK: - Cards and their order

    /// Chat exports and Files and links appear only while they hold something; they are never offered (plan 3.1). A
    /// source's page can still be opened by a hand-off (a drop, the palette): `narrow` keeps the open one.
    static let offeredOnlyWhenHeld: Set<String> = ["chat-exports", "files"]

    static func isOffered(_ row: SourceCatalogRow) -> Bool {
        !offeredOnlyWhenHeld.contains(row.id) || row.status == .connected
    }

    /// Every card, in the page's order: what needs the person (signed out, needs access), then what is connected, most
    /// recently read first, then what is not connected — the app already on this Mac first, then the catalogue's own order
    /// (category, then entry). Pure: the same rows always give the same order, and a row never moves unless its status did.
    static func cards(rows: [SourceCatalogRow], streams: ResolvedStreams) -> [Card] {
        let base = SourceCategory.allCases.flatMap { category in rows.filter { $0.entry.category == category } }
        let place = Dictionary(uniqueKeysWithValues: base.enumerated().map { ($0.element.id, $0.offset) })
        let built = base.filter(isOffered).map { card($0, streams: streams.streams($0.id)) }
        return built.sorted { a, b in
            if a.group != b.group { return a.group < b.group }
            switch a.group {
            case .connected:
                // Dated reads first, newest on top; an undated one keeps the catalogue's place below them.
                switch (a.lastRead, b.lastRead) {
                case let (x?, y?) where x != y: return x > y
                case (.some, .none): return true
                case (.none, .some): return false
                default: break
                }
            case .notConnected:
                if a.row.suggested != b.row.suggested { return a.row.suggested }
            case .needsYou:
                break
            }
            return place[a.id, default: 0] < place[b.id, default: 0]
        }
    }

    static func card(_ row: SourceCatalogRow, streams: [ResolvedStream]) -> Card {
        let group: Group = row.needsYou ? .needsYou : (row.isConnectedHere ? .connected : .notConnected)
        let read = ([row.lastSync] + streams.map(\.stream.lastReadAt)).compactMap { $0 }.max()
        return Card(row: row, group: group, streams: streams, line: line(streams), lastRead: read)
    }

    /// The streams that are on, with their counts; with none on, what the source could read, as names only. A stream the
    /// backend calls unavailable is neither: nothing is promised that cannot be read.
    static func line(_ streams: [ResolvedStream]) -> StreamsLine? {
        let on = streams.filter { $0.stream.state == .on }
        if !on.isEmpty {
            return StreamsLine(ink: .on, parts: on.map { .init(label: $0.stream.label, count: $0.stream.count) },
                               folders: on.reduce(0) { $0 + $1.stream.folderCount })
        }
        let readable = streams.filter { $0.stream.state == .off }
        guard !readable.isEmpty else { return nil }
        return StreamsLine(ink: .available, parts: readable.map { .init(label: $0.stream.label, count: nil) }, folders: 0)
    }

    // MARK: - Tabs

    /// A tab is a kind (`SourceShelf`) or All (nil), the shape `TextTabs` and DR-45's "tap the active one returns to
    /// All" already speak. The count is what the tab holds before the find narrows it, so the tabs do not jump as the
    /// person types.
    struct Tab: Identifiable, Equatable {
        let shelf: SourceShelf?
        let count: Int
        var id: String { shelf?.rawValue ?? "all" }
        var label: String { shelf?.title ?? Copy.Streams.all }
    }

    static func tabs(_ cards: [Card]) -> [Tab] {
        [Tab(shelf: nil, count: cards.count)]
            + SourceShelf.allCases.compactMap { shelf in
                let n = cards.filter { $0.shelf == shelf }.count
                return n == 0 ? nil : Tab(shelf: shelf, count: n)
            }
    }

    /// The tab to draw: the chosen one while it still holds a card, else All (a source that left it never strands the page).
    static func effectiveTab(_ chosen: SourceShelf?, cards: [Card]) -> SourceShelf? {
        guard let chosen, cards.contains(where: { $0.shelf == chosen }) else { return nil }
        return chosen
    }

    // MARK: - Find and the arrow keys

    /// What the visible tab draws and the arrow keys walk: the cards of the tab in the page's order, or — while words are
    /// typed — the cards that match them, best first, through the app's one ranker (no network, no model). A stream's
    /// own name finds its source ("likes" finds X).
    static func visible(_ cards: [Card], tab: SourceShelf?, query: String) -> [Card] {
        let inTab = tab.map { shelf in cards.filter { $0.shelf == shelf } } ?? cards
        guard SourceGrid.isSearching(query) else { return inTab }
        let place = Dictionary(uniqueKeysWithValues: inTab.enumerated().map { ($0.element.id, Double($0.offset)) })
        return QuickMatch.rank(inTab, query: query, fields: fields, tieBreak: { -(place[$0.id] ?? 0) },
                               name: { $0.row.entry.title }).map(\.item)
    }

    private static func fields(_ card: Card) -> [QuickMatch.Field] {
        let row = card.row
        return [QuickMatch.Field(row.entry.title, weight: QuickMatch.Weight.name)]
            + (SourceGrid.alsoKnownAs[row.id] ?? []).map { QuickMatch.Field($0, weight: QuickMatch.Weight.intent) }
            + card.streams.map { QuickMatch.Field($0.stream.label, weight: QuickMatch.Weight.intent) }
            + [QuickMatch.Field(row.entry.category.title, weight: QuickMatch.Weight.keyword),
               QuickMatch.Field(row.entry.shelf.title, weight: QuickMatch.Weight.keyword)]
    }

    /// The card a key press lands on: the one the arrows moved to while it is still shown, else the first.
    static func highlighted(_ visible: [Card], cursor: String?) -> String? {
        if let cursor, visible.contains(where: { $0.id == cursor }) { return cursor }
        return visible.first?.id
    }

    /// One step along the visible cards, stopping at either end.
    static func moved(_ delta: Int, in visible: [Card], cursor: String?) -> String? {
        let ids = visible.map(\.id)
        guard let current = highlighted(visible, cursor: cursor), let at = ids.firstIndex(of: current) else { return nil }
        return ids[min(max(at + delta, 0), ids.count - 1)]
    }

    // MARK: - Beside an open source

    /// The narrow DR-34 rows beside an open source (`SourceCatalogRowView`): the same cards in the same order, with no
    /// tab or find (those are the root's). The open source is always among them, whatever the offered-only rule says.
    static func narrow(rows: [SourceCatalogRow], streams: ResolvedStreams, open: String?) -> [Card] {
        let shown = cards(rows: rows, streams: streams)
        guard let open, !shown.contains(where: { $0.id == open }),
              let row = rows.first(where: { $0.id == open }) else { return shown }
        return shown + [card(row, streams: streams.streams(open))]
    }
}
