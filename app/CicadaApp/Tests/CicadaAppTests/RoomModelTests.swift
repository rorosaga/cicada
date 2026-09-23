import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §8 — the room's interaction state: the ladder's stepping, the
/// perk's rate limit, beats gated by the matrix and by Reduce Motion, and a
/// pointer that writes only what changed.
@MainActor
final class RoomModelTests: XCTestCase {

    private let scene = deskSceneLayout(pointSize: 120, uiScale: 1.0)
    private var spots: [DeskHotspot: CGRect] { deskHotspots(scene) }
    /// Top-left points (what `onContinuousHover` reports) at 5 pt cells.
    private let overWorm = CGPoint(x: 200, y: 70)
    private let overLamp = CGPoint(x: 20, y: 100)

    func test_theLadderStepsThroughThenReturnsToTheStatus() {
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: nil, count: 3), 0)
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: 1, count: 3), 2)
        XCTAssertNil(RoomModel.nextAnswerIndex(after: 2, count: 3), "one click past the last rung")
        XCTAssertNil(RoomModel.nextAnswerIndex(after: nil, count: 0))
        // Review r1: the ladder shrank under an open answer — restart, never a
        // silent click.
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: 3, count: 3), 0)
        XCTAssertEqual(RoomModel.nextAnswerIndex(after: 7, count: 2), 0)
    }

    func test_aPokeTalks_exceptInWordsOnlyStates() {
        let room = RoomModel()
        XCTAssertEqual(room.poke(answerCount: 2, state: .happy, reduceMotion: false), 0)
        XCTAssertEqual(room.reaction?.kind, .talk)
        let quiet = RoomModel()
        _ = quiet.poke(answerCount: 2, state: .error, reduceMotion: false)
        XCTAssertNil(quiet.reaction, "error answers in words only (§6.4)")
        let still = RoomModel()
        _ = still.poke(answerCount: 2, state: .happy, reduceMotion: true)
        XCTAssertNil(still.reaction, "Reduce Motion: no beats")
        XCTAssertEqual(still.answerIndex, 0, "…but the answer still shows")
    }

    func test_thePerkIsRateLimited() {
        let t0 = Date(timeIntervalSinceReferenceDate: 1_000)
        XCTAssertTrue(RoomModel.shouldPerk(lastPerkAt: nil, now: t0))
        XCTAssertFalse(RoomModel.shouldPerk(lastPerkAt: t0, now: t0.addingTimeInterval(1.9)))
        XCTAssertTrue(RoomModel.shouldPerk(lastPerkAt: t0, now: t0.addingTimeInterval(SleepMotion.perkCooldown)))
    }

    func test_reachingTheWormPerksOnce_andTheGazeFollows() {
        let room = RoomModel()
        let t0 = Date(timeIntervalSinceReferenceDate: 1_000)
        room.pointer(at: overLamp, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertTrue(room.pointerInRoom)
        XCTAssertEqual(room.gaze, .left)
        XCTAssertNil(room.reaction)
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertEqual(room.gaze, .center)
        XCTAssertEqual(room.reaction?.kind, .perk)
        let first = room.reaction?.id
        room.pointer(at: overLamp, scene: scene, spots: spots, state: .awake, now: t0.addingTimeInterval(0.5), reduceMotion: false)
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .awake, now: t0.addingTimeInterval(1), reduceMotion: false)
        XCTAssertEqual(room.reaction?.id, first, "within the cooldown, no second perk")
        room.pointer(at: nil, scene: scene, spots: spots, state: .awake, now: t0, reduceMotion: false)
        XCTAssertFalse(room.pointerInRoom)
        XCTAssertEqual(room.gaze, .center)
    }

    func test_aSleepingWormNeverPerks() {
        let room = RoomModel()
        room.pointer(at: overWorm, scene: scene, spots: spots, state: .sleeping(stage: 2), now: .now, reduceMotion: false)
        XCTAssertNil(room.reaction)
    }

    func test_dismissReturnsToTheStatus() {
        let room = RoomModel()
        _ = room.poke(answerCount: 3, state: .happy, reduceMotion: true)
        room.dismissAnswers()
        XCTAssertNil(room.answerIndex)
    }

    /// I5 / I7 — an out-of-order exit never clears the neighbour's highlight.
    func test_hoverSurvivesAnOutOfOrderExit() {
        let room = RoomModel()
        room.hover(origin: "claude-code", inside: true)
        room.hover(origin: "rss", inside: true)
        room.hover(origin: "claude-code", inside: false)
        XCTAssertEqual(room.hoveredOrigin, "rss")
        room.hover(origin: "rss", inside: false)
        XCTAssertNil(room.hoveredOrigin)
    }
}
