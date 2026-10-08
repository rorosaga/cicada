import XCTest
@testable import CicadaApp

/// #244 serves an entity's newest `HistoryPaging.window` changes (`historyTruncated` when there are more) and
/// `GET /entities/{id}/history?skip=N` the older ones. "Older changes" pages through them.
final class HistoryPagingTests: XCTestCase {
    private func rows(_ hashes: [String]) -> [EntityHistoryEntry] {
        hashes.map { EntityHistoryEntry(date: Date(timeIntervalSince1970: 0), changeType: .updated, description: "", author: "cicada",
                                        commitHash: $0) }
    }

    func testOlderChangesStartAfterTheServedWindowAndAdvanceByWhatCameBack() {
        var paging = HistoryPaging(truncated: true)
        XCTAssertTrue(paging.hasMore)
        XCTAssertEqual(paging.nextSkip, HistoryPaging.window, "the first older page starts after the served window")
        let page = rows((0..<HistoryPaging.window).map { "p\($0)" })
        paging.received(page)
        XCTAssertEqual(paging.nextSkip, 2 * HistoryPaging.window)
        XCTAssertTrue(paging.hasMore, "a full page may have more behind it")
        paging.received(rows(["q0", "q1"]))
        XCTAssertFalse(paging.hasMore, "a short page is the end")
        XCTAssertFalse(HistoryPaging(truncated: false).hasMore, "nothing older when the page was complete")
    }

    /// Newest first, and a commit the served page already carried (the window's older survivors) is never listed twice.
    func testOlderRowsFollowTheNewestOnesOnce() {
        let shown = rows(["a", "b", "old-survivor"])
        let merged = HistoryPaging.merge(shown, older: rows(["c", "old-survivor", "d"]))
        XCTAssertEqual(merged.map(\.commitHash), ["a", "b", "old-survivor", "c", "d"])
    }

    func testThePageSaysWhenItLeftOlderChangesOut() throws {
        let json = #"{"id":"a","name":"A","type":"concept","status":"active","confidence":1,"created":"","lastReferenced":"","decayRate":0,"markdownContent":"","historyTruncated":true}"#
        XCTAssertTrue(try JSONDecoder().decode(Entity.self, from: Data(json.utf8)).historyTruncated)
        let older = json.replacingOccurrences(of: #","historyTruncated":true"#, with: "")
        XCTAssertFalse(try JSONDecoder().decode(Entity.self, from: Data(older.utf8)).historyTruncated)
    }
}
