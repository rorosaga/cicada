import XCTest
@testable import CicadaApp

/// Track Z §6.1 — the worm's poses and reactions, checked the way
/// `BookwormSpriteTests` checks its states: dimensions and palette, the
/// signature rows, and — the rule response art lives under — **a reaction
/// never hides a state mark** (R-Z1): the nightcap, the stage dots and the
/// red pupils persist through every response.
final class BookwormPoseSpriteTests: XCTestCase {

    /// Every state the Sleep page can show.
    static let pageStates: [BookwormState] =
        [.awake, .happy, .reading, .hungry, .digesting, .error] + (1...5).map { .sleeping(stage: $0) }

    private var allowed: Set<Character> { Set(BookwormPalette.colors.keys).union(["."]) }

    private func everyFrame(_ state: BookwormState) -> [(String, PixelGrid)] {
        BookwormLook.reachable(for: state).flatMap { look in
            BookwormSprites.frames(for: state, look: look).frames.enumerated().map {
                ("\(state.spriteKey) \(look.keySegment ?? "idle") #\($0.offset)", $0.element)
            }
        }
    }

    func test_everyLookFrameIs24x24AndInThePalette() {
        for state in Self.pageStates {
            for (name, frame) in everyFrame(state) {
                XCTAssertEqual(frame.count, 24, name)
                for row in frame {
                    XCTAssertEqual(row.count, 24, name)
                    for ch in row where !allowed.contains(ch) { XCTFail("\(name): '\(ch)'") }
                }
            }
        }
    }

    /// R-Z4 / design §6.1: `.idle` is byte-identical to today's frames.
    func test_theIdleLookIsTodaysFrames() {
        for state in Self.pageStates + [.curious(count: 3)] {
            XCTAssertEqual(BookwormSprites.frames(for: state, pose: .idle).frames,
                           BookwormSprites.frames(for: state).frames, state.spriteKey)
            XCTAssertEqual(BookwormSprites.frames(for: state, look: .idle).interval,
                           BookwormSprites.frames(for: state).interval)
        }
        XCTAssertEqual(BookwormSprites.eyes(), BookwormSprites.eyes(gaze: .center))
    }

    /// Three gazes change only the pupil rows (7–8 open, 7 half-lidded); the
    /// rim rows, which `BookwormSpriteTests` pins, never move.
    func test_gazeMovesOnlyThePupils() {
        let left = BookwormSprites.eyes(gaze: .left), right = BookwormSprites.eyes(gaze: .right)
        let center = BookwormSprites.eyes()
        XCTAssertEqual(left[2], "....obaoowwabaoowwabo...")
        XCTAssertEqual(right[2], "....obawwooabawwooabo...")
        XCTAssertEqual(center[2], "....obawoowabawoowabo...")
        for i in [0, 1, 4] { XCTAssertEqual(left[i], center[i]); XCTAssertEqual(right[i], center[i]) }
        XCTAssertEqual(BookwormSprites.eyes(pupil: "e", gaze: .left), BookwormSprites.eyes(pupil: "e"),
                       "red eyes are state art and never look away")
    }

    /// The glasses rims (rows 5 and 9) are the character's signature. Every
    /// frame this task AUTHORS keeps them, after undoing at most the one-cell
    /// hop/crouch or the head's one-cell shake. The idle frames and cheer's
    /// borrowed happy frames (whose big sparkle crosses the rim on frame 1)
    /// are existing art, pinned by `BookwormSpriteTests`.
    func test_theGlassesRimsSurviveEveryNewFrame() {
        let top = String(BookwormSprites.awakeBase[5].prefix(21))
        let bottom = String(BookwormSprites.awakeBase[9].prefix(21))
        for state in Self.pageStates {
            let authored = BookwormLook.reachable(for: state).filter { look in
                if look == .idle { return false }
                if case .reaction(.cheer, _) = look { return false }
                return true
            }
            let frames = authored.flatMap { look in
                BookwormSprites.frames(for: state, look: look).frames.map { ("\(state.spriteKey) \(look.keySegment ?? "")", $0) }
            }
            for (name, frame) in frames {
                let found = [-1, 0, 1].contains { dy in [-1, 0, 1].contains { dx in
                    let f = BookwormSprites.shiftRows(BookwormSprites.shift(frame, dy: -dy), 0..<24, dx: -dx)
                    return String(f[5].prefix(21)) == top && String(f[9].prefix(21)) == bottom
                } }
                XCTAssertTrue(found, name)
            }
        }
    }

    /// R-Z1 — the cap on every `.sleeping`/`.reading` frame (a capped state's
    /// hop is a one-cell crouch, Z-P11, so the cap may sit one row lower).
    func test_theNightcapSurvivesEveryLook() {
        let cap: [(Int, Int, Character)] = [(0, 10, "z"), (2, 5, "w"), (2, 16, "w"), (3, 3, "w")]
        for state in [BookwormState.reading] + (1...5).map({ .sleeping(stage: $0) }) {
            for (name, frame) in everyFrame(state) {
                let capped = [0, 1].contains { dy in cap.allSatisfy { Array(frame[$0.0 + dy])[$0.1] == $0.2 } }
                XCTAssertTrue(capped, name)
            }
        }
    }

    func test_theStageDotsAndTheRedPupilsSurviveEveryLook() {
        for stage in 1...5 {
            for (name, frame) in everyFrame(.sleeping(stage: stage)) {
                XCTAssertEqual(frame[23], BookwormSprites.stageDots(stage)[23], name)
            }
        }
        for (name, frame) in everyFrame(.error) {
            XCTAssertTrue(frame.joined().contains("e"), name)
            XCTAssertFalse(frame[7].contains("oo"), "\(name): no dark pupils on an error frame")
        }
    }

    /// Reading keeps its book on every frame — gulp lowers it (Z-P12).
    func test_theReadingBookSurvivesEveryLook() {
        for (name, frame) in everyFrame(.reading) {
            XCTAssertTrue((14...21).contains { r in String(Array(frame[r])[8...16]) == "aaaaaaaaa" }, name)
        }
    }

    /// §6.4 — `.sleeping`, `.error` and `.digesting` have no gaze variants.
    func test_suppressedStatesIgnoreThePointer() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            for gaze in Gaze.allCases {
                XCTAssertEqual(BookwormSprites.frames(for: state, pose: .attentive(gaze)).frames,
                               BookwormSprites.frames(for: state).frames, state.spriteKey)
            }
        }
    }

    /// The state × response matrix (§6.4), including the Z-P12 reconciliation.
    func test_theMatrix() {
        XCTAssertEqual(Self.pageStates.filter(\.acceptsGaze).map(\.caseName), ["awake", "happy", "reading", "hungry"])
        XCTAssertTrue(BookwormState.digesting.acceptsDropPose)
        XCTAssertFalse(BookwormState.sleeping(stage: 1).acceptsDropPose)
        XCTAssertTrue(BookwormState.sleeping(stage: 3).allows(.talk), "it talks in its sleep")
        XCTAssertFalse(BookwormState.error.allows(.talk), "words only")
        XCTAssertTrue(BookwormState.digesting.allows(.gulp))
        XCTAssertTrue(BookwormState.digesting.allows(.cheer))
        XCTAssertTrue(BookwormState.happy.allows(.cheer))
        XCTAssertFalse(BookwormState.reading.allows(.cheer))
        XCTAssertFalse(BookwormState.digesting.allows(.perk))
        XCTAssertTrue(BookwormSprites.reactionFrames(.talk, for: .error, gaze: .center).isEmpty)
        XCTAssertFalse(BookwormState.curious(count: 3).acceptsGaze, "the menu bar never gets a pose")
    }

    /// Every beat is at most three frames at 0.12 s — ≤ 0.36 s, inside the
    /// page's 400 ms budget (R-Z12).
    func test_everyBeatFitsTheMotionBudget() {
        XCTAssertEqual(BookwormSprites.reactionInterval, 0.12)
        for state in Self.pageStates {
            for reaction in BookwormReaction.allCases where state.allows(reaction) {
                let n = BookwormSprites.reactionFrames(reaction, for: state, gaze: .left).count
                XCTAssertTrue((2...3).contains(n), "\(reaction) on \(state.spriteKey)")
                XCTAssertLessThanOrEqual(Double(n) * BookwormSprites.reactionInterval, SleepMotion.maxDuration)
            }
        }
    }

    /// The attentive loop costs no more ticks than idle: the state's own
    /// interval, a blink on the fourth frame; the drop poses loop at 0.4 s.
    func test_theLoopsKeepTheirIntervals() {
        let attentive = BookwormSprites.frames(for: .hungry, pose: .attentive(.left))
        XCTAssertEqual(attentive.interval, BookwormSprites.frames(for: .hungry).interval)
        XCTAssertEqual(attentive.frames.count, 4)
        XCTAssertEqual(attentive.frames[0], attentive.frames[2])
        XCTAssertNotEqual(attentive.frames[0], attentive.frames[3])
        XCTAssertEqual(BookwormSprites.frames(for: .awake, pose: .expectant(.right)).interval, 0.4)
        XCTAssertEqual(BookwormSprites.frames(for: .awake, pose: .eager).frames.count, 2)
    }
}
