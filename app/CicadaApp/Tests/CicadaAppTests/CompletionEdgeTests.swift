import XCTest
@testable import CicadaApp

/// Track Z §6.5 / I17 / I18 — a real completion cheers once and links to what
/// it changed; a cancel or a failure does neither. The edge and its commit
/// arrive apart (Z-P17): `SleepViewModel`'s poll sets `status` idle BEFORE
/// `load()` refetches history, so the edge records a baseline and the history
/// change that brings a new sleep commit resolves it.
@MainActor
final class CompletionEdgeTests: XCTestCase {

    private func entry(_ hash: String, kind: String = "sleep") throws -> SleepHistoryEntry {
        try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(
            #"{"commitHash":"\#(hash)","date":"2026-09-20","message":"x","kind":"\#(kind)"}"#.utf8))
    }

    func test_onlyARealCompletionCounts() {
        XCTAssertTrue(isRealCompletion(old: "running", new: "idle", cancelled: false, error: nil))
        XCTAssertTrue(isRealCompletion(old: "running", new: "idle", cancelled: false, error: ""))
        XCTAssertFalse(isRealCompletion(old: "running", new: "idle", cancelled: true, error: nil), "a cancel files nothing")
        XCTAssertFalse(isRealCompletion(old: "running", new: "idle", cancelled: false, error: "boom"), "a failure is news, not a cheer")
        XCTAssertFalse(isRealCompletion(old: "idle", new: "idle", cancelled: false, error: nil))
        XCTAssertFalse(isRealCompletion(old: nil, new: "idle", cancelled: false, error: nil), "a first load is not an edge")
    }

    func test_theCommitIsTheNewestSleepCommitThatWasNotThereBefore() throws {
        let before = [try entry("old")]
        let after = [try entry("inbox9", kind: "inbox"), try entry("decay9", kind: "decay"), try entry("c0ffee"), try entry("old")]
        XCTAssertEqual(completedCommit(baseline: "old", history: after), "c0ffee")
        XCTAssertNil(completedCommit(baseline: "old", history: before), "history has not caught up yet")
        XCTAssertEqual(completedCommit(baseline: nil, history: [try entry("first")]), "first", "the bank's first cycle")
    }

    func test_theLinkLivesFromTheCommitToTheClick() throws {
        let room = RoomModel()
        room.recordCompletion(baseline: "old", at: Date())
        XCTAssertNil(room.resolveCompletion(history: [try entry("old")]))
        XCTAssertNotNil(room.pendingCompletion, "still waiting for the commit")
        XCTAssertEqual(room.resolveCompletion(history: [try entry("c0ffee"), try entry("old")]), "c0ffee")
        XCTAssertEqual(room.recentCycleCommit, "c0ffee")
        XCTAssertNil(room.pendingCompletion)
        XCTAssertNil(room.resolveCompletion(history: [try entry("c0ffee")]), "resolves once")
        XCTAssertEqual(room.followWhatChanged(), "c0ffee")
        XCTAssertNil(room.recentCycleCommit, "cleared when clicked")
    }

    func test_theNextCycleClearsTheLinkAndAnyPendingEdge() {
        let room = RoomModel()
        room.recentCycleCommit = "c0ffee"
        room.recordCompletion(baseline: "c0ffee", at: Date())
        room.cycleStarted()
        XCTAssertNil(room.recentCycleCommit)
        XCTAssertNil(room.pendingCompletion)
    }
}
