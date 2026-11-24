import XCTest
@testable import CicadaApp

/// G245 (plan 3.1) — the root's cards: one truth for the state word, the order, the two lines, the tabs, find and keys.
@MainActor
final class SourcesRootTests: XCTestCase {
    private let now = SourceStreamsFixture.now
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!

    private func channel(_ id: String, error: String? = nil, lastSync: String? = nil, connected: Bool = true,
                         count: Int = 0) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: connected, count: count, lastSync: lastSync, lastError: error)
    }

    private func rows(channels: [SourceChannel] = [], localReaders: [String: Bool] = [:],
                      savedLists: Set<String> = [], waitingOn: [String: String] = [:],
                      suggested: Set<String> = [], localAgent: Bool = true,
                      savedListsRead: Set<String>? = nil,
                      browserReads: [String: BrowserRead] = [:]) -> [SourceCatalogRow] {
        let entries = SourceCatalog.entries(browsers: [chrome], wisprPresent: false, hexPresent: false,
                                            overview: [], channels: channels)
        return SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                  localReaders: localReaders, savedListsOn: savedLists, localAgent: localAgent,
                                  savedListsRead: savedListsRead, waitingOn: waitingOn, suggested: suggested,
                                  browserReads: browserReads)
    }

    private func streams(_ app: StreamAppState = StreamAppState()) throws -> ResolvedStreams {
        let entries = SourceCatalog.entries(browsers: [chrome], wisprPresent: false, hexPresent: false, overview: [])
        return SourceStreamOverlay.resolve(try SourceStreamsFixture.load(), app: app, entries: entries, now: now)
    }

    private func ids(_ cards: [SourcesRoot.Card]) -> [String] { cards.map(\.id) }

    // MARK: One truth

    func testTheCardsWordToneAndGroupComeFromTheCatalogueRowUnchanged() throws {
        let all = rows(channels: [channel("reddit"), channel("github", error: "401 token expired")],
                       waitingOn: ["calendar-local": Copy.sourceNeedsAccess])
        let cards = SourcesRoot.cards(rows: all, streams: try streams())
        for card in cards {
            XCTAssertEqual(card.word, card.row.word)
            XCTAssertEqual(card.tone, card.row.tone)
        }
        let eyebrow = SourceCatalog.connectedCount(all)
        XCTAssertEqual(cards.filter { $0.group == .connected }.count, eyebrow,
                       "the eyebrow's N connected and the connected group can never disagree")
        XCTAssertEqual(Set(cards.filter { $0.group == .needsYou }.map(\.id)), Set(all.filter(\.needsYou).map(\.id)))
        XCTAssertEqual(SourcesRoot.card(try XCTUnwrap(all.first { $0.id == "github" }), streams: []).group, .needsYou)
    }

    func testAStreamNeverChangesWhichGroupACardIsIn() throws {
        // The fixture says x reads fine; the catalogue says x is on and waiting for an agent: the catalogue wins.
        let all = rows(savedLists: ["x"], localAgent: false)
        let card = try XCTUnwrap(SourcesRoot.cards(rows: all, streams: try streams()).first { $0.id == "x" })
        XCTAssertEqual(card.group, .needsYou)
        XCTAssertEqual(card.row.status, .waitingForAgent)
    }

    // MARK: Order

    func testNeedsYouThenConnectedByMostRecentReadThenNotConnected() throws {
        let all = rows(
            channels: [channel("reddit", lastSync: "2026-11-20T10:00:00Z"),
                       channel("pinterest", lastSync: "2026-11-23T10:00:00Z"),
                       channel("github", error: "401 token expired")],
            localReaders: ["calendar-local": true, "contacts-local": true])
        let cards = SourcesRoot.cards(rows: all, streams: ResolvedStreams())
        let groups = cards.map(\.group)
        XCTAssertEqual(groups, groups.sorted(), "needs you, connected, not connected — never interleaved")
        let connected = cards.filter { $0.group == .connected }
        XCTAssertGreaterThanOrEqual(connected.count, 2)
        let dated = connected.compactMap(\.lastRead)
        XCTAssertEqual(dated, dated.sorted(by: >), "connected: most recently read first")
        let reddit = try XCTUnwrap(ids(connected).firstIndex(of: "reddit"))
        let pinterest = try XCTUnwrap(ids(connected).firstIndex(of: "pinterest"))
        XCTAssertLessThan(pinterest, reddit)
        XCTAssertEqual(cards.first?.id, "github", "what needs the person leads")
    }

    func testAStreamsRecentReadCountsForTheOrder() throws {
        // x's streams were read this morning; reddit's channel synced days ago: x leads the connected group.
        let all = rows(channels: [channel("reddit", lastSync: "2026-11-20T10:00:00Z"),
                                  channel("x", lastSync: "2026-11-01T10:00:00Z")])
        let cards = SourcesRoot.cards(rows: all, streams: try streams())
        let connected = ids(cards.filter { $0.group == .connected })
        XCTAssertLessThan(try XCTUnwrap(connected.firstIndex(of: "x")), try XCTUnwrap(connected.firstIndex(of: "reddit")))
        XCTAssertEqual(cards.first { $0.id == "x" }?.lastRead, ISODate.parse("2026-11-24T08:10:00Z"))
    }

    func testNotConnectedKeepsTheCataloguesOrderWithTheAppOnThisMacFirst() throws {
        let plain = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams()).filter { $0.group == .notConnected }
        let suggested = SourcesRoot.cards(rows: rows(suggested: [WhatsAppWatcher.channel]), streams: ResolvedStreams())
            .filter { $0.group == .notConnected }
        XCTAssertEqual(suggested.first?.id, WhatsAppWatcher.channel)
        XCTAssertEqual(ids(suggested).filter { $0 != WhatsAppWatcher.channel },
                       ids(plain).filter { $0 != WhatsAppWatcher.channel }, "the rest never moves")
    }

    func testTheSameRowsGiveTheSameOrderEveryTime() throws {
        let all = rows(channels: [channel("reddit", lastSync: "2026-11-20T10:00:00Z")], localReaders: ["calendar-local": true])
        let resolved = try streams()
        XCTAssertEqual(ids(SourcesRoot.cards(rows: all, streams: resolved)), ids(SourcesRoot.cards(rows: all, streams: resolved)),
                       "a card never moves unless its status did")
    }

    func testChatExportsAndFilesAppearOnlyWhileTheyHoldSomething() throws {
        let empty = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams())
        XCTAssertFalse(ids(empty).contains("chat-exports"))
        XCTAssertFalse(ids(empty).contains("files"))
        let held = SourcesRoot.cards(rows: rows(channels: [channel("chat-export:claude", count: 4), channel("files")]),
                                     streams: ResolvedStreams())
        XCTAssertTrue(ids(held).contains("chat-exports"))
        XCTAssertTrue(ids(held).contains("files"))
        // An open page is always reachable, whatever the rule says: a drop opens Files and links.
        let narrow = SourcesRoot.narrow(rows: rows(), streams: ResolvedStreams(), open: "files")
        XCTAssertEqual(narrow.last?.id, "files")
        XCTAssertEqual(ids(SourcesRoot.narrow(rows: rows(), streams: ResolvedStreams(), open: nil)), ids(empty))
    }

    // MARK: The two lines

    func testALineNamesTheStreamsThatAreOnWithTheirCountsAndFolders() throws {
        let all = rows(channels: [channel("x")])
        let x = try XCTUnwrap(SourcesRoot.cards(rows: all, streams: try streams()).first { $0.id == "x" })
        let line = try XCTUnwrap(x.line)
        XCTAssertEqual(line.ink, .on)
        XCTAssertEqual(line.parts.map(\.label), ["Bookmarks", "Likes"], "off streams are not on the line")
        XCTAssertEqual(line.text(locale: Locale(identifier: "en_US")), "Bookmarks 214 · Likes 1,032 · 3 folders")
        XCTAssertEqual(line.text(locale: Locale(identifier: "de_DE")), "Bookmarks 214 · Likes 1.032 · 3 folders",
                       "counts in the reader's locale (R-S18)")
    }

    func testASourceNotConnectedListsWhatItCanReadAsNamesOnly() throws {
        let youtubeOff = SourceStreamsResponse(sources: [SourceStreamsSource(id: "linkedin", streams: [
            SourceStream(id: "linkedin.saved", label: "Saved posts", state: .off),
            SourceStream(id: "linkedin.connections", label: "Connections", kind: .connections, state: .off)])])
        let resolved = SourceStreamOverlay.resolve(youtubeOff, app: StreamAppState(), entries: [], now: now)
        let card = try XCTUnwrap(SourcesRoot.cards(rows: rows(), streams: resolved).first { $0.id == "linkedin" })
        XCTAssertEqual(card.group, .notConnected)
        XCTAssertEqual(card.line?.ink, .available)
        XCTAssertEqual(card.line?.text(), "Saved posts · Connections")
    }

    /// The streams may say a list is on while the catalogue (the one truth) says the source is not connected: the card
    /// follows the catalogue, so it never shows counts or "on" for a source it offers to connect.
    func testASourceNotConnectedNeverShowsCountsEvenWhenItsStreamsSayOn() throws {
        let said = SourceStreamsResponse(sources: [SourceStreamsSource(id: "linkedin", streams: [
            SourceStream(id: "linkedin.saved", label: "Saved posts", state: .on, count: 41),
            SourceStream(id: "linkedin.gone", label: "Gone", state: .unavailable)])])
        let resolved = SourceStreamOverlay.resolve(said, app: StreamAppState(), entries: [], now: now)
        let card = try XCTUnwrap(SourcesRoot.cards(rows: rows(), streams: resolved).first { $0.id == "linkedin" })
        XCTAssertEqual(card.group, .notConnected)
        XCTAssertEqual(card.line?.ink, .available)
        XCTAssertEqual(card.line?.text(), "Saved posts", "names only: no count, no unavailable stream")
    }

    func testAnUnavailableStreamIsNeverPromised() throws {
        let resolved = try streams()
        let messages = try XCTUnwrap(SourcesRoot.cards(rows: rows(), streams: resolved).first { $0.id == "imessage" })
        XCTAssertNil(messages.line, "its only stream is unavailable: nothing to say beneath the name")
    }

    func testASourceWithNoStreamsAnswerHasNoSecondLine() throws {
        let cards = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams())
        XCTAssertTrue(cards.allSatisfy { $0.line == nil && $0.streams.isEmpty }, "the catalogue row stands alone")
    }

    func testASingleFolderIsSaidInTheSingular() {
        XCTAssertEqual(Copy.Streams.folders(1), "1 folder")
        XCTAssertEqual(Copy.Streams.folders(12), "12 folders")
    }

    func testANotConnectedCardSaysNothingOfWhenItLastRead() throws {
        let cards = SourcesRoot.cards(rows: rows(), streams: try streams())
        XCTAssertTrue(cards.filter { $0.group == .notConnected }.allSatisfy { !$0.showsLastRead })
    }

    // MARK: Tabs

    func testTabsAreTheKindsEachWithItsCountAndAnEmptyKindIsNotDrawn() throws {
        let cards = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams())
        let tabs = SourcesRoot.tabs(cards)
        XCTAssertNil(tabs.first?.shelf, "All leads")
        XCTAssertEqual(tabs.first?.count, cards.count)
        XCTAssertEqual(tabs.first?.label, "All")
        XCTAssertEqual(tabs.dropFirst().map(\.shelf), SourceShelf.allCases.filter { shelf in cards.contains { $0.shelf == shelf } })
        for tab in tabs.dropFirst() { XCTAssertEqual(tab.count, cards.filter { $0.shelf == tab.shelf }.count) }
        let without = SourcesRoot.tabs(cards.filter { $0.shelf != .work })
        XCTAssertFalse(without.contains { $0.shelf == .work })
    }

    func testATabThatEmptiedFallsBackToAll() throws {
        let cards = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams())
        XCTAssertEqual(SourcesRoot.effectiveTab(.saved, cards: cards), .saved)
        XCTAssertNil(SourcesRoot.effectiveTab(.saved, cards: cards.filter { $0.shelf != .saved }))
        XCTAssertNil(SourcesRoot.effectiveTab(nil, cards: cards))
    }

    func testTheVisibleTabHoldsOnlyItsKindInThePagesOrder() throws {
        let cards = SourcesRoot.cards(rows: rows(channels: [channel("reddit")]), streams: ResolvedStreams())
        let saved = SourcesRoot.visible(cards, tab: .saved, query: "")
        XCTAssertTrue(saved.allSatisfy { $0.shelf == .saved })
        XCTAssertEqual(ids(saved), ids(cards.filter { $0.shelf == .saved }))
        XCTAssertEqual(ids(SourcesRoot.visible(cards, tab: nil, query: "  ")), ids(cards), "spaces are no search")
    }

    // MARK: Find and keys

    func testFindRanksTheNameFirstAndAlsoFindsASourceByAStreamsName() throws {
        let cards = SourcesRoot.cards(rows: rows(channels: [channel("x")]), streams: try streams())
        XCTAssertEqual(SourcesRoot.visible(cards, tab: nil, query: "x").first?.id, "x", "its own name leads")
        let byStream = ids(SourcesRoot.visible(cards, tab: nil, query: "likes"))
        XCTAssertTrue(byStream.contains("x"), "a stream's name finds its source")
        XCTAssertTrue(ids(SourcesRoot.visible(cards, tab: nil, query: "twitter")).contains("x"), "and so does what it is also called")
        XCTAssertEqual(SourcesRoot.visible(cards, tab: nil, query: "zzzzqqq"), [])
    }

    func testFindStaysInsideTheVisibleTab() throws {
        let cards = SourcesRoot.cards(rows: rows(channels: [channel("x")]), streams: try streams())
        XCTAssertFalse(ids(SourcesRoot.visible(cards, tab: .conversations, query: "likes")).contains("x"))
        XCTAssertTrue(ids(SourcesRoot.visible(cards, tab: .saved, query: "likes")).contains("x"))
    }

    func testTheArrowKeysWalkTheVisibleTabsOrderAndStopAtEitherEnd() throws {
        let cards = SourcesRoot.cards(rows: rows(), streams: ResolvedStreams())
        let visible = SourcesRoot.visible(cards, tab: .saved, query: "")
        let order = ids(visible)
        XCTAssertGreaterThan(order.count, 3)
        XCTAssertEqual(SourcesRoot.highlighted(visible, cursor: nil), order.first, "no cursor: the first")
        XCTAssertEqual(SourcesRoot.highlighted(visible, cursor: "calendar-local"), order.first,
                       "a cursor on a card another tab holds falls to the first, never to nothing")
        var cursor = SourcesRoot.highlighted(visible, cursor: nil)
        var walked = [cursor!]
        for _ in 0..<(order.count + 3) {
            cursor = SourcesRoot.moved(1, in: visible, cursor: cursor)
            if walked.last != cursor { walked.append(cursor!) }
        }
        XCTAssertEqual(walked, order, "down walks the visible order once and stops at the end")
        XCTAssertEqual(SourcesRoot.moved(-1, in: visible, cursor: order.first), order.first)
        XCTAssertNil(SourcesRoot.moved(1, in: [], cursor: nil))
    }

    func testTheNarrowListIsTheRootsOrderWithNoTabOrFind() throws {
        let all = rows(channels: [channel("reddit", lastSync: "2026-11-20T10:00:00Z")])
        let resolved = try streams()
        XCTAssertEqual(ids(SourcesRoot.narrow(rows: all, streams: resolved, open: "reddit")),
                       ids(SourcesRoot.cards(rows: all, streams: resolved)))
    }
}
