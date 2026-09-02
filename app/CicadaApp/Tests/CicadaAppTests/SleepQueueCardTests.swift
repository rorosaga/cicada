import XCTest
@testable import CicadaApp

/// PR #19 review: `SleepQueueCard` used to treat a missing `store.status`
/// snapshot as a confirmed zero queue once `isLoading` cleared — including
/// right after a failed first fetch, which reads "All caught up" for a queue
/// that was never actually checked. `loadState` distinguishes the three cases
/// so only a genuinely landed snapshot may render "All caught up" / a count.
final class SleepQueueCardTests: XCTestCase {

    private func status(unprocessed: Int) -> StatusSnapshot {
        StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: unprocessed, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)
    }

    func testLoadStateIsLoadingWhileTheFetchIsInFlight() {
        XCTAssertEqual(SleepQueueCard.loadState(status: nil, isLoading: true, error: nil), .loading)
    }

    /// A failed first fetch (no snapshot, no longer refreshing, a latched
    /// domain error) must surface that failure — never silently read as "0
    /// queued" / "All caught up".
    func testLoadStateIsFailedAfterAFailedFetchWithNoSnapshot() {
        XCTAssertEqual(
            SleepQueueCard.loadState(status: nil, isLoading: false, error: "Couldn't load status"),
            .failed("Couldn't load status")
        )
    }

    /// No snapshot, not refreshing, no latched error yet — the fetch simply
    /// hasn't started. Must not be mistaken for a confirmed empty queue.
    func testLoadStateFallsBackToLoadingBeforeTheFetchHasStarted() {
        XCTAssertEqual(SleepQueueCard.loadState(status: nil, isLoading: false, error: nil), .loading)
    }

    /// Once a snapshot has actually landed, its count is authoritative — this
    /// is the only path "All caught up" (count == 0) may render for, and it
    /// must win over stale isLoading/error flags left over from a prior
    /// attempt.
    func testLoadStateIsLoadedOnceASnapshotLands() {
        XCTAssertEqual(
            SleepQueueCard.loadState(status: status(unprocessed: 3), isLoading: true, error: "stale error"),
            .loaded(count: 3)
        )
        XCTAssertEqual(SleepQueueCard.loadState(status: status(unprocessed: 0), isLoading: false, error: nil), .loaded(count: 0))
    }
}
