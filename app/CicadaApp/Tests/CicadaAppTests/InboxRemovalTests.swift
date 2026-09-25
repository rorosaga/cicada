import XCTest
@testable import CicadaApp

/// G129 slice 2: the pure filter `ChannelSourceView`'s Deletions subsection
/// runs on `store.visibleInbox` (Task 4) — tested here without a view.
final class InboxRemovalTests: XCTestCase {
    private func item(id: String, channel: String?, kind: InboxKind = .removal) throws -> InboxItem {
        let json = """
        {"id":"\(id)","kind":"\(kind.rawValue)","requiredInput":"choice","status":"pending","priority":0.4,
         "entityId":"e","entityName":"E","title":"t","createdDate":"2026-09-05","options":[],
         "channel":\(channel.map { "\"\($0)\"" } ?? "null")}
        """
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testOpenRemovalsFiltersByKindAndChannel() throws {
        let a = try item(id: "a", channel: "chrome-bookmarks")
        let b = try item(id: "b", channel: "safari-bookmarks")
        let c = try item(id: "c", channel: "chrome-bookmarks", kind: .decay)
        let result = InboxItem.openRemovals(in: [a, b, c], channelId: "chrome-bookmarks")
        XCTAssertEqual(result.map(\.id), ["a"])
    }

    func testOpenRemovalsEmptyWhenNoneMatch() throws {
        // `InboxItem` is not `Equatable` — assert emptiness, not array equality.
        let a = try item(id: "a", channel: "safari-bookmarks")
        XCTAssertTrue(InboxItem.openRemovals(in: [a], channelId: "chrome-bookmarks").isEmpty)
    }
}
