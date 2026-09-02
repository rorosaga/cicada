import XCTest
@testable import CicadaApp

/// G107: the menu-bar state machine gains `error` (the last Sleep cycle
/// failed) and the precedence that keeps it honest — a failed cycle shows red
/// eyes at once, not after six seconds of chewing (ruling R6).
final class BookwormStateTests: XCTestCase {

    private func snapshot(
        status: String = "idle", stage: Int = 0, error: String? = nil,
        inboxTotal: Int = 0, lastIngestedAt: String? = nil
    ) -> StatusSnapshot {
        StatusSnapshot(
            sleep: .init(status: status, stage: stage, totalStages: 5, cycleId: nil, error: error),
            inbox: .init(total: inboxTotal, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: lastIngestedAt),
            lastSleepAt: nil, nextSleepAt: nil
        )
    }

    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private var fresh: String { ISO8601DateFormatter().string(from: now.addingTimeInterval(-3600)) }

    func testErrorOutranksDigestingHungryCuriousAndHappy() {
        let s = snapshot(error: "RuntimeError: boom", inboxTotal: 5)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: now.addingTimeInterval(-1), now: now), .error)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .error)
    }

    func testRunningCycleOutranksError() {
        let s = snapshot(status: "running", stage: 2, error: "stale error from the previous cycle")
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .sleeping(stage: 2))
    }

    func testEmptyErrorStringIsNotAnError() {
        let s = snapshot(error: "", lastIngestedAt: fresh)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .happy)
    }

    func testExistingPrecedenceIsUnchangedWithoutAnError() {
        XCTAssertEqual(deriveBookwormState(snapshot(status: "running", stage: 9), justFinishedAt: nil, now: now), .sleeping(stage: 5))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: now.addingTimeInterval(-2), now: now), .digesting)
        XCTAssertEqual(deriveBookwormState(snapshot(inboxTotal: 3), justFinishedAt: nil, now: now), .hungry)
        XCTAssertEqual(deriveBookwormState(snapshot(inboxTotal: 3, lastIngestedAt: fresh), justFinishedAt: nil, now: now), .curious(count: 3))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: nil, now: now), .happy)
    }

    func testErrorCopyAndIdentity() {
        XCTAssertEqual(BookwormState.error.title, "Error")
        XCTAssertEqual(BookwormState.error.detail, "last sleep cycle failed")
        XCTAssertEqual(BookwormState.error.caseName, "error")
        XCTAssertEqual(BookwormState.error.spriteKey, "error")
        XCTAssertEqual(BookwormState.error.badgeCount, 0)
    }

    func testErrorFramesHaveRedPupilsAndMove() {
        let (frames, interval) = BookwormSprites.frames(for: .error)
        XCTAssertEqual(frames.count, 2)
        XCTAssertNotEqual(frames[0], frames[1])
        XCTAssertEqual(frames[0][7], "....obaweewabaweewabo...")
        XCTAssertTrue(frames[1].joined().contains("e"), "the glitch frame keeps the red eyes")
        XCTAssertEqual(interval, 0.5, accuracy: 0.001)
    }
}
