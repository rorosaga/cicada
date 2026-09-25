import XCTest
@testable import CicadaApp

/// §5.3 / DR-27…DR-30 / R-DI8…R-DI10 — which question is open, pure. `@MainActor` because
/// `InboxResolve` (inside `ResolveGrace`) conforms to the main-actor `Mutation` protocol.
@MainActor
final class InboxColumnsTests: XCTestCase {
    private func item(_ id: String, kind: String = "conflict", priority: Double = 0.5, created: String = "2026-09-01",
                      episode: String? = nil) throws -> InboxItem {
        let cause = episode.map { #","cause":{"episodeId":"\#($0)","excerpt":"x","mentionOffsets":[[0,1]],"start":0,"tier":"claim"}"# } ?? ""
        return try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"\#(id)","priority":\#(priority),"createdDate":"\#(created)","entityId":"alpha-project"\#(cause)}"#.utf8))
    }

    func testTheOrderIsPriorityThenNewest() throws {
        let a = try item("a", priority: 0.2), b = try item("b", priority: 0.9), c = try item("c", priority: 0.2, created: "2026-09-10")
        XCTAssertEqual(InboxColumns.visible([a, b, c], filter: nil).map(\.id), ["b", "c", "a"])
        XCTAssertEqual(InboxColumns.visible([a, b, try item("d", kind: "decay")], filter: .decay).map(\.id), ["d"])
    }

    /// DR-29 — the Reader closes on a swap unless the new question cites the same conversation.
    func testASwapKeepsTheReaderOnlyForTheSameConversation() throws {
        let same = try item("a", episode: "ep_1"), other = try item("b", episode: "ep_2"), none = try item("c")
        var c = InboxColumns()
        XCTAssertEqual(c.select(same, in: [same, other, none], readerEpisode: nil), .keep, "no Reader, nothing to do")
        let effect = c.select(same, in: [same, other, none], readerEpisode: "ep_1")
        guard case .refocus(let t) = effect else { return XCTFail("same conversation re-lands in place (R-DI9)") }
        XCTAssertEqual(t.episode, "ep_1")
        XCTAssertEqual(c.select(other, in: [same, other, none], readerEpisode: "ep_1"), .close)
        XCTAssertEqual(c.select(none, in: [same, other, none], readerEpisode: "ep_1"), .close)
        XCTAssertEqual(c.openId, "c")
    }

    /// DR-29 — after an answer the next row opens at once; the last answer returns to STATE 0.
    func testAfterAnAnswerTheNextRowOpensAndTheLastReturnsToStateZero() throws {
        let a = try item("a"), b = try item("b"), c = try item("c")
        var cols = InboxColumns()
        _ = cols.select(b, in: [a, b, c], readerEpisode: nil)
        cols.afterAnswer("b", remaining: [a, c])
        XCTAssertEqual(cols.openId, "c", "the row that moved into the answered row's place")
        cols.afterAnswer("c", remaining: [a])
        XCTAssertEqual(cols.openId, "a", "the last row answered: the one before it")
        cols.afterAnswer("a", remaining: [])
        XCTAssertNil(cols.openId)
        cols.afterAnswer("zzz", remaining: [a])
        XCTAssertNil(cols.openId, "an answer from elsewhere (the Sources page) moves nothing")
    }

    func testUndoReopensTheQuestionAndClearsAFilterThatHidesIt() throws {
        let d = try item("d", kind: "decay")
        var cols = InboxColumns()
        cols.kindFilter = .conflict
        cols.undo(d)
        XCTAssertEqual(cols.openId, "d")
        XCTAssertNil(cols.kindFilter)
    }

    /// A question answered elsewhere (MCP, an organic Sleep resolve) hands the column to its neighbour.
    func testAVanishedQuestionHandsOverToItsNeighbourAndAnEmptiedTabReturnsToAll() throws {
        let a = try item("a"), b = try item("b"), c = try item("c")
        var cols = InboxColumns()
        _ = cols.select(b, in: [a, b, c], readerEpisode: nil)
        cols.reconcile(visible: [a, c], kinds: [.conflict])
        XCTAssertEqual(cols.openId, "c")
        cols.kindFilter = .decay
        cols.reconcile(visible: [a, c], kinds: [.conflict])
        XCTAssertNil(cols.kindFilter)
        cols.reconcile(visible: [], kinds: [])
        XCTAssertNil(cols.openId)
    }

    /// DR-45 — a tab keeps the open question when it shows it, else opens its first; STATE 0 stays 0.
    func testATabSwitchKeepsOrReplacesTheOpenQuestion() throws {
        let a = try item("a"), d = try item("d", kind: "decay")
        var cols = InboxColumns()
        cols.filter(.decay, visibleAfter: [d])
        XCTAssertNil(cols.openId)
        _ = cols.select(a, in: [a, d], readerEpisode: nil)
        cols.filter(.decay, visibleAfter: [d])
        XCTAssertEqual(cols.openId, "d")
        cols.filter(nil, visibleAfter: [a, d])
        XCTAssertEqual(cols.openId, "d")
    }

    /// DR-28 — Esc closes the rightmost open thing (the card has already closed its field).
    func testEscapeClosesTheReaderThenTheQuestion() throws {
        var cols = InboxColumns()
        XCTAssertEqual(cols.escape(readerOpen: false), .none)
        XCTAssertEqual(cols.escape(readerOpen: true), .closeReader, "R-DI8 — STATE 0 + Reader")
        _ = cols.select(try item("a"), in: [], readerEpisode: nil)
        XCTAssertEqual(cols.escape(readerOpen: true), .closeReader)
        XCTAssertEqual(cols.escape(readerOpen: false), .closeQuestion)
    }

    /// DR-68 — ↑/↓ on the list: the neighbour, the first or last from nothing, clamped at the ends.
    func testArrowsWalkTheListAndStopAtItsEnds() throws {
        let a = try item("a"), b = try item("b")
        var cols = InboxColumns()
        XCTAssertEqual(cols.neighbour(1, in: [a, b])?.id, "a")
        XCTAssertEqual(cols.neighbour(-1, in: [a, b])?.id, "b")
        _ = cols.select(b, in: [a, b], readerEpisode: nil)
        XCTAssertEqual(cols.neighbour(1, in: [a, b])?.id, "b")
        XCTAssertEqual(cols.neighbour(-1, in: [a, b])?.id, "a")
    }

    /// G136 / DR-30 — a palette or Home hand-off: every kind shown, that question open.
    func testALandingClearsTheFilterAndOpensTheQuestion() {
        var cols = InboxColumns()
        cols.kindFilter = .decay
        cols.land("inbox-007")
        XCTAssertEqual(cols.openId, "inbox-007")
        XCTAssertNil(cols.kindFilter)
    }

    /// DR-42 — the Undo row takes the answered row's place in the list.
    func testTheUndoRowSitsWhereTheAnsweredRowWas() throws {
        let a = try item("a", priority: 0.9), b = try item("b", priority: 0.5), c = try item("c", priority: 0.1)
        let held = ResolveGrace(resolve: InboxResolve(id: "b", action: "resolve", optionKey: "x"), label: "Answered · x",
                                shortLabel: "Answered", question: "b", kind: .conflict, channel: nil, bank: "demo", token: 1)
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: held, snapshot: [a, b, c], filter: nil).map(\.id), ["a", "b", "c"])
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: held, snapshot: [a, b, c], filter: .decay).map(\.id), ["a", "c"])
        XCTAssertEqual(InboxRows.entries(visible: [a, c], held: nil, snapshot: [a, b, c], filter: nil).map(\.id), ["a", "c"])
    }

    /// R-DI26 / DR-31 — a one-line row's fixed slots go before they would overflow the column.
    func testAWideRowDropsItsSlotsBeforeItOverflows() {
        XCTAssertEqual(InboxRowSlots.of(listUnits: 1384), .init(entity: true, source: true))
        XCTAssertEqual(InboxRowSlots.of(listUnits: 680), .init(entity: true, source: true))
        XCTAssertEqual(InboxRowSlots.of(listUnits: 632), .init(entity: false, source: true), "1200 labelled + Reader")
        XCTAssertEqual(InboxRowSlots.of(listUnits: 441), .init(entity: false, source: false), "1.4× beside a Reader")
    }

    /// DR-25 — "Inbox · 6 pending", "Inbox · 1 of 6 · Conflict".
    func testTheEyebrowAndTheTabs() throws {
        let a = try item("a"), b = try item("b"), d = try item("d", kind: "decay", priority: 0.1)
        XCTAssertEqual(InboxEyebrow.text(visible: [a, b, d], openId: nil), "Inbox · 3 pending")
        XCTAssertEqual(InboxEyebrow.text(visible: [a, b, d], openId: "b"), "Inbox · 2 of 3 · Conflict")
        XCTAssertEqual(InboxEyebrow.text(visible: [], openId: nil), "Inbox")
        let tabs = InboxTabs.tabs([a, b, d])
        XCTAssertEqual(tabs.map(\.label), ["All", "Decay", "Conflict"], "present kinds, in the stable order")
        XCTAssertEqual(tabs.map(\.count), [3, 1, 2])
        XCTAssertEqual(tabs.map(\.id), [nil, .decay, .conflict])
    }
}
