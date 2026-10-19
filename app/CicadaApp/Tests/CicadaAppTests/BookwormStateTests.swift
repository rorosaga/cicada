import XCTest
@testable import CicadaApp

/// G107: the menu-bar state machine gains `error` (the last Sleep cycle
/// failed) and the precedence that keeps it honest — a failed cycle shows red
/// eyes at once, not after six seconds of chewing (ruling R6).
final class BookwormStateTests: XCTestCase {

    private func snapshot(
        status: String = "idle", stage: Int = 0, error: String? = nil,
        inboxTotal: Int = 0, lastIngestedAt: String? = nil, unprocessed: Int = 0, readable: Int? = nil
    ) -> StatusSnapshot {
        StatusSnapshot(
            sleep: .init(status: status, stage: stage, totalStages: 5, cycleId: nil, error: error),
            inbox: .init(total: inboxTotal, byKind: [:]),
            episodes: .init(unprocessed: unprocessed, lastIngestedAt: lastIngestedAt, readable: readable),
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
        let s = snapshot(status: "running", stage: 1, error: "stale error from the previous cycle")
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .sleeping(stage: 2))
    }

    func testEmptyErrorStringIsNotAnError() {
        let s = snapshot(error: "", lastIngestedAt: fresh)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .happy)
    }

    func testExistingPrecedenceIsUnchangedWithoutAnError() {
        XCTAssertEqual(deriveBookwormState(snapshot(status: "running", stage: 9), justFinishedAt: nil, now: now), .sleeping(stage: 5))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: now.addingTimeInterval(-2), now: now), .digesting)
        XCTAssertEqual(deriveBookwormState(snapshot(readable: 3), justFinishedAt: nil, now: now), .hungry)
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh, readable: 3), justFinishedAt: nil, now: now), .curious(count: 3))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: nil, now: now), .happy)
    }

    /// Owner 2026-10-19: the badge is what waits for Sleep — `/status` `episodes.readable`, the count Sleep itself would
    /// read — never the inbox. 190 questions and nothing to read is no badge.
    func testTheBadgeCountsWhatWaitsForSleepNotTheInbox() {
        let s = snapshot(inboxTotal: 190, lastIngestedAt: fresh, unprocessed: 14, readable: 12)
        XCTAssertEqual(s.waitingForSleep, 12, "readable, not the parked-inclusive unprocessed count")
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .curious(count: 12))
        let questionsOnly = snapshot(inboxTotal: 190, lastIngestedAt: fresh, unprocessed: 2, readable: 0)
        let mood = deriveBookwormState(questionsOnly, justFinishedAt: nil, now: now)
        XCTAssertEqual(mood, .happy, "0 waiting → no badge, however full the inbox")
        XCTAssertEqual(mood.badgeCount, 0)
        XCTAssertEqual(BookwormOverlays.grid(for: mood), BookwormOverlays.blank(), "no badge pixels at 0")
        XCTAssertEqual(MenuBarManager.toolTip(for: .curious(count: 12)), "Cicada — 12 conversations waiting for Sleep")
    }

    /// An older backend (and an older on-disk cache) sends no `readable`: its `unprocessed` is the nearest count.
    func testAnOlderBackendFallsBackToUnprocessed() throws {
        let s = snapshot(lastIngestedAt: fresh, unprocessed: 5)
        XCTAssertEqual(s.waitingForSleep, 5)
        let json = #"{"sleep":{"status":"idle","stage":0,"totalStages":5},"inbox":{"total":3,"byKind":{}},"#
            + #""episodes":{"unprocessed":4}}"#
        let decoded = try JSONDecoder().decode(StatusSnapshot.self, from: Data(json.utf8))
        XCTAssertNil(decoded.episodes.readable)
        XCTAssertEqual(decoded.waitingForSleep, 4)
        let current = #"{"sleep":{"status":"idle","stage":0,"totalStages":5},"inbox":{"total":3,"byKind":{}},"#
            + #""episodes":{"unprocessed":4,"readable":2}}"#
        XCTAssertEqual(try JSONDecoder().decode(StatusSnapshot.self, from: Data(current.utf8)).waitingForSleep, 2)
    }

    func testErrorCopyAndIdentity() {
        XCTAssertEqual(BookwormState.error.title, "Error")
        XCTAssertEqual(BookwormState.error.detail, "last sleep cycle failed")
        XCTAssertEqual(BookwormState.error.caseName, "error")
        XCTAssertEqual(BookwormState.error.spriteKey, "error")
        XCTAssertEqual(BookwormState.error.badgeCount, 0)
    }

    /// G125 Task 5: `.reading` copy/identity — the badge/stage accessors
    /// treat it like every other non-curious/non-sleeping case (0 for both),
    /// and `spriteKey` falls to `caseName` alone (no baked count or stage).
    func testReadingCopyAndIdentity() {
        XCTAssertEqual(BookwormState.reading.title, "Reading")
        XCTAssertEqual(BookwormState.reading.detail, "reading what's waiting")
        XCTAssertEqual(BookwormState.reading.caseName, "reading")
        XCTAssertEqual(BookwormState.reading.spriteKey, "reading")
        XCTAssertEqual(BookwormState.reading.badgeCount, 0)
        XCTAssertEqual(BookwormState.reading.stageNumber, 0)
    }

    func testErrorFramesHaveBlackXEyesAndDropAndMove() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-error")
        let clip = try SpriteTestAssets.clip(sheet, "idle")
        XCTAssertGreaterThanOrEqual(Set(clip.order.map { sheet.rectIndex[$0] }).count, 2)
        let palette = try SpriteTestAssets.palette()
        for frame in clip.order {
            let plane = try SpriteTestAssets.plane(sheet, frame: frame)
            try SpriteTestAssets.assertErrorMarks(plane, small: false, palette: palette)
        }
    }

    /// Task 3: the menu bar ticks for EVERY state (all are multi-frame — the
    /// brief's "always moving") and holds frame 0 only under Reduce Motion
    /// (ruling R7). The rule is a pure static so it is testable without an
    /// `NSStatusItem`. 18 pt is ruling R3.
    func testMenuBarAnimatesEveryStateUnlessReduceMotion() throws {
        _ = try SpriteTestAssets.sheet("bookworm-small")
        for state in BookwormSpriteTests.states {
            XCTAssertTrue(MenuBarManager.animates(state, reduceMotion: false), state.caseName)
            XCTAssertFalse(MenuBarManager.animates(state, reduceMotion: true), state.caseName)
        }
        XCTAssertEqual(MenuBarManager.spritePointSize, 18)
    }
}
