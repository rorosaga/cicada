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

    /// What the person's one button on a card names, when the card has something for them to do (plan 3.1).
    enum Fix: Equatable, Sendable {
        case signIn, giveAccess, tryAgain, connectYourAI

        var title: String {
            switch self {
            case .signIn: Copy.Catalog.signIn
            case .giveAccess: Copy.Streams.giveAccess
            case .tryAgain: Copy.tryAgain
            case .connectYourAI: Copy.Streams.openAgents
            }
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

        /// The word at the card's trailing edge. A source not connected says nothing (its label and its Connect button
        /// say it), except where the catalogue has something to add: the app is gone, or a list is on and not read yet.
        var trailingWord: (word: String, tone: StatusWord.Tone)? {
            switch group {
            case .needsYou, .connected:
                return (word, tone)
            case .notConnected:
                if row.notInstalled { return (Copy.SourcePage.notInstalledRow, .off) }
                if row.browser?.state == .notReadYet { return (word, tone) }
                return nil
            }
        }

        /// The one button of a needs-you card, naming the fix; nil on any other card.
        var fix: Fix? { group == .needsYou ? SourcesRoot.fix(row) : nil }

        /// A source not connected can be connected from its card, unless there is nothing to connect: its app is gone,
        /// or its list is already on and waiting for a first read.
        var connectable: Bool {
            group == .notConnected && !row.notInstalled && row.browser?.state != .notReadYet
        }
    }

    /// The fix a needs-you card names. Pure over the catalogue row, so the word and the button never disagree.
    static func fix(_ row: SourceCatalogRow) -> Fix? {
        if row.notInstalled { return nil }
        if let waiting = row.waitingOn { return waiting == Copy.sourceNeedsAccess ? .giveAccess : .tryAgain }
        if row.status == .waitingForAgent { return .connectYourAI }
        if row.browser?.state == .couldntRead { return .tryAgain }
        if row.browser?.state == .signedOut || row.status == .needsSignIn { return .signIn }
        return nil
    }

    /// The page's state on the root: the words in the field, the card the arrows moved to, and the chosen kind. Kept by
    /// the page, so what was typed outlives an opened source and Esc from it returns to the same results.
    struct State: Equatable {
        var text = ""
        /// The card ↑/↓ moved to; nil is the best result while searching (`highlighted`).
        var cursor: String?
        /// The kind chosen in the tabs; nil is All.
        var tab: SourceShelf?

        /// New words start at the best result again. Return commits the field with the words it already holds just
        /// before it submits, and that must not lose the card the arrows moved to.
        mutating func typed(_ words: String) {
            guard words != text else { return }
            text = words
            cursor = nil
        }

        var searching: Bool { SourceGrid.isSearching(text) }

        /// What the page draws and the keys walk: the chosen kind's cards, or the ranked find.
        func visible(_ cards: [Card]) -> [Card] {
            SourcesRoot.visible(cards, tab: SourcesRoot.effectiveTab(tab, cards: cards), query: text)
        }

        /// The card that is lit: while words are typed the best result, once an arrow moved the one it moved to; at rest
        /// none (a page nobody has touched shows no selection).
        func lit(_ cards: [Card]) -> String? {
            searching || cursor != nil ? SourcesRoot.highlighted(visible(cards), cursor: cursor) : nil
        }

        /// ↑/↓ along the visible cards, stopping at either end.
        mutating func walk(_ delta: Int, in cards: [Card]) {
            let shown = visible(cards)
            guard !shown.isEmpty else { return }
            cursor = SourcesRoot.moved(delta, in: shown, cursor: cursor)
        }

        /// A hand-off (the palette, a notch, Sleep's *Open in Sources*) did not ask for the words left in the field.
        mutating func clearFind() {
            text = ""
            cursor = nil
        }
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
        // A source not connected lists what it can read, names only, whatever the streams say: counts and "on" belong to
        // a source that is read, and the catalogue (one truth) says it is not.
        let second = group == .notConnected ? readable(streams) : line(streams)
        return Card(row: row, group: group, streams: streams, line: second, lastRead: read)
    }

    /// The streams that are on, with their counts; with none on, what the source could read, as names only. A stream the
    /// backend calls unavailable is neither: nothing is promised that cannot be read.
    static func line(_ streams: [ResolvedStream]) -> StreamsLine? {
        let on = streams.filter { $0.stream.state == .on }
        if !on.isEmpty {
            return StreamsLine(ink: .on, parts: on.map { .init(label: $0.stream.label, count: $0.stream.count) },
                               folders: on.reduce(0) { $0 + $1.stream.folderCount })
        }
        return readable(streams)
    }

    /// What a source could read: its streams by name (counts and folders left out), tertiary ink; nil with none.
    static func readable(_ streams: [ResolvedStream]) -> StreamsLine? {
        let names = streams.filter { $0.stream.state == .off || $0.stream.state == .on }
        guard !names.isEmpty else { return nil }
        return StreamsLine(ink: .available, parts: names.map { .init(label: $0.stream.label, count: nil) }, folders: 0)
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

    // MARK: - Where the one label goes

    /// What the root draws under the tabs: the cards that are the person's (needs you, then connected) with no heading,
    /// then what is not connected under one label — and no label when it would head the only run, or while words are
    /// typed (a ranked find is one flat list). DR-81: a run with nothing in it is not drawn.
    static func sections(_ visible: [Card], searching: Bool) -> [(label: String?, cards: [Card])] {
        guard !searching else { return visible.isEmpty ? [] : [(nil, visible)] }
        let mine = visible.filter { $0.group != .notConnected }
        let rest = visible.filter { $0.group == .notConnected }
        var out: [(label: String?, cards: [Card])] = []
        if !mine.isEmpty { out.append((nil, mine)) }
        if !rest.isEmpty { out.append((mine.isEmpty ? nil : Copy.Streams.notConnected, rest)) }
        return out
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
