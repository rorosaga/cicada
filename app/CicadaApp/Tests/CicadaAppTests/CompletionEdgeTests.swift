import XCTest
@testable import CicadaApp

/// Track Z §6.5 / I17 / I18 — a real completion cheers once and links to what
/// it changed; a cancel or a failure does neither. The edge and its commit
/// can arrive in either order: `SleepViewModel`'s poll sets `status` idle
/// BEFORE `load()` refetches history (Z-P17), but the backend commits before
/// its post-commit tail ends, so a reconcile load can bring the commit while
/// status still says running (Task 8 review r1). The baseline is taken at the
/// start edge, and whichever of the end edge or the history change sees the
/// new commit first resolves it — once.
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
        room.cycleStarted(baseline: "c0ffee", historyLoaded: true)
        XCTAssertNil(room.recentCycleCommit)
        XCTAssertNil(room.pendingCompletion)
    }

    /// Task 8 review r1 (HIGH): the backend commits in `_finalize`, then runs
    /// the engine-independent tail with status still "running"; a reconcile
    /// `load()` in that window brings the new commit BEFORE the idle edge.
    /// The start-edge baseline still resolves it — exactly once, at the edge.
    func test_aCommitThatArrivesWhileStillRunningResolvesAtTheIdleEdge() throws {
        let room = RoomModel()
        room.cycleStarted(baseline: "old", historyLoaded: true)
        let midTail = [try entry("new"), try entry("old")]
        XCTAssertNil(room.resolveCompletion(history: midTail), "no edge yet: running, nothing to resolve")
        XCTAssertEqual(room.cycleEnded(real: true, edgeBaseline: "new", history: midTail), "new",
                       "the idle-edge baseline is already the new commit; the start baseline is not")
        XCTAssertEqual(room.recentCycleCommit, "new")
        XCTAssertNil(room.pendingCompletion)
        XCTAssertNil(room.resolveCompletion(history: midTail), "resolves once")
        XCTAssertNil(room.runStart, "consumed by the end edge")
    }

    /// The ordinary path still works: the commit lands after the edge.
    func test_aCommitThatArrivesAfterTheEdgeResolvesOnTheHistoryChange() throws {
        let room = RoomModel()
        room.cycleStarted(baseline: "old", historyLoaded: true)
        XCTAssertNil(room.cycleEnded(real: true, edgeBaseline: "old", history: [try entry("old")]))
        XCTAssertNotNil(room.pendingCompletion)
        XCTAssertEqual(room.resolveCompletion(history: [try entry("new"), try entry("old")]), "new")
    }

    /// A page opened mid-run sees the start edge before its first history
    /// fetch lands: an empty list there means "not yet", so the start
    /// baseline is not trusted and the edge-time one is used — which errs
    /// toward no cheer, never toward presenting an older cycle's commit.
    func test_aStartSeenBeforeHistoryLoadedFallsBackToTheEdgeBaseline() throws {
        let room = RoomModel()
        room.cycleStarted(baseline: nil, historyLoaded: false)
        XCTAssertNil(room.runStart)
        let history = [try entry("prev")]
        XCTAssertNil(room.cycleEnded(real: true, edgeBaseline: "prev", history: history),
                     "the previous cycle's commit is never 'what changed'")
        XCTAssertEqual(room.resolveCompletion(history: [try entry("new"), try entry("prev")]), "new")
    }

    /// A loaded, genuinely empty history (the bank's first cycle) keeps its
    /// nil baseline — `nil` from the start edge is not "missing".
    func test_theFirstCycleOfALoadedEmptyBankResolves() throws {
        let room = RoomModel()
        room.cycleStarted(baseline: nil, historyLoaded: true)
        XCTAssertEqual(room.cycleEnded(real: true, edgeBaseline: "first", history: [try entry("first")]), "first")
    }

    /// A cancel or failure records nothing, and consumes the start baseline
    /// so a later cycle whose start this page missed cannot inherit it.
    func test_aCancelConsumesTheStartAndRecordsNothing() throws {
        let room = RoomModel()
        room.cycleStarted(baseline: "old", historyLoaded: true)
        XCTAssertNil(room.cycleEnded(real: false, edgeBaseline: "old", history: [try entry("old")]))
        XCTAssertNil(room.runStart)
        XCTAssertNil(room.pendingCompletion)
    }

    /// Task 8 review r1 (LOW): an edge that committed nothing must not stay
    /// armed for a later cycle whose running edge the page never saw.
    func test_aPendingEdgeExpires() throws {
        let room = RoomModel()
        let edge = Date(timeIntervalSince1970: 1_000_000)
        room.recordCompletion(baseline: "old", at: edge)
        XCTAssertNil(room.resolveCompletion(history: [try entry("old")], now: edge.addingTimeInterval(5)))
        XCTAssertNotNil(room.pendingCompletion, "still inside its lifetime")
        let late = edge.addingTimeInterval(RoomModel.pendingLifetime + 1)
        XCTAssertNil(room.resolveCompletion(history: [try entry("later"), try entry("old")], now: late),
                     "a later cycle's commit is not this edge's")
        XCTAssertNil(room.pendingCompletion, "dropped")
        XCTAssertNil(room.recentCycleCommit)
    }
}
