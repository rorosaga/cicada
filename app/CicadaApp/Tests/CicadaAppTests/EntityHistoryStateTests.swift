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

    // MARK: PR #19 review — a failed fetch must not read as "no commits"

    /// A thrown `fetchEntityHistory` must not be represented the same way as
    /// a successful-but-empty response (`fetched: []`) — that used to claim
    /// "no commits touch this page" for a dead backend, and permanently
    /// block a retry (the view's guard only re-fetches while
    /// `fetchedHistory == nil`, and the old code coerced a failure to `[]`).
    func testAFailedFetchIsDistinctFromAConfirmedEmptyOne() {
        let empty = HistoryTabState.resolve(embedded: [], fetched: [], failed: false)
        let failed = HistoryTabState.resolve(embedded: [], fetched: nil, failed: true)

        guard case .empty = empty else { return XCTFail("expected .empty for a confirmed empty response") }
        guard case .error = failed else { return XCTFail("expected .error for a thrown fetch") }
    }

    /// `failed` wins over a `nil` fetch — otherwise a failure falls through
    /// to `.loading` and spins forever instead of offering a retry.
    func testFailedTakesPriorityOverAStillNilFetch() {
        guard case .error = HistoryTabState.resolve(embedded: [], fetched: nil, failed: true) else {
            return XCTFail("expected .error")
        }
    }

    /// Embedded history (already on the entity payload) wins even over a
    /// failed fetch — the tab has real data to show and should show it.
    func testEmbeddedHistoryWinsOverAFailedFetch() {
        guard case .entries(let rows) = HistoryTabState.resolve(embedded: [entry("created")], fetched: nil, failed: true) else {
            return XCTFail("expected .entries")
        }
        XCTAssertEqual(rows.map(\.description), ["created"])
    }

    /// The retry transition: a failed attempt resolves to `.error`; the next
    /// attempt clears `failed` and goes back to `.loading` while in flight,
    /// then lands on `.entries` once the retry succeeds. Mirrors exactly what
    /// `EntityDetailCard.loadHistoryIfNeeded()` does to its `@State` on a
    /// second call.
    func testRetryTransitionsFromErrorThroughLoadingToEntries() {
        guard case .error = HistoryTabState.resolve(embedded: [], fetched: nil, failed: true) else {
            return XCTFail("expected the first attempt to resolve to .error")
        }

        // `loadHistoryIfNeeded` clears `historyLoadFailed` before awaiting the
        // retry — `fetchedHistory` is still nil while the retry is in flight.
        guard case .loading = HistoryTabState.resolve(embedded: [], fetched: nil, failed: false) else {
            return XCTFail("expected the retry-in-flight state to be .loading")
        }

        guard case .entries(let rows) = HistoryTabState.resolve(embedded: [], fetched: [entry("a")], failed: false) else {
            return XCTFail("expected the successful retry to resolve to .entries")
        }
        XCTAssertEqual(rows.map(\.description), ["a"])
    }
}
