import XCTest
@testable import CicadaApp

/// G68 §2.10 — `entity.history` is `[]` both before the full entity body has
/// landed and when the page genuinely has no commits. The History tab has to
/// tell those apart or it lies for the length of a round-trip.
final class EntityHistoryStateTests: XCTestCase {

    private func entry(_ description: String) -> EntityHistoryEntry {
        EntityHistoryEntry(date: Date(), changeType: .created, description: description)
    }

    func testNothingEmbeddedAndNothingFetchedYetIsLoading() {
        guard case .loading = HistoryTabState.resolve(embedded: [], fetched: nil) else {
            return XCTFail("expected .loading")
        }
    }

    func testAFetchThatCameBackWithNothingIsEmpty() {
        guard case .empty = HistoryTabState.resolve(embedded: [], fetched: []) else {
            return XCTFail("expected .empty")
        }
    }

    /// History that arrived on the entity payload wins immediately — no
    /// spinner for data we already have.
    func testEmbeddedHistoryRendersWithoutWaitingForAFetch() {
        guard case .entries(let rows) = HistoryTabState.resolve(embedded: [entry("created")], fetched: nil) else {
            return XCTFail("expected .entries")
        }
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].description, "created")
    }

    func testAFetchFillsInWhenTheEntityPayloadCarriedNone() {
        guard case .entries(let rows) = HistoryTabState.resolve(embedded: [], fetched: [entry("a"), entry("b")]) else {
            return XCTFail("expected .entries")
        }
        XCTAssertEqual(rows.map(\.description), ["a", "b"])
    }
}
