import XCTest
@testable import CicadaApp

/// Track Z §6.1 renderer + Z-P10 — the key gains one `look` segment that is
/// omitted for idle, so every pre-Z4 key is byte-identical
/// (`BookwormRendererTests` passes unmodified), and the page's reachable key
/// set stays under the design's bound so the menu bar's frames are never
/// collateral damage of a wipe (P13).
@MainActor
final class BookwormLookRendererTests: XCTestCase {

    func test_idleKeysAreByteIdentical() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .reading, look: .idle, frameIndex: 2, pointSize: 120), "reading|2|120")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .sleeping(stage: 3), look: .idle, frameIndex: 1, pointSize: 18),
                       BookwormRenderer.cacheKey(state: .sleeping(stage: 3), frameIndex: 1, pointSize: 18))
    }

    func test_lookKeysNameTheLook() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .happy, look: .pose(.attentive(.left)), frameIndex: 0, pointSize: 120),
                       "happy|attentive.left|0|120")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .happy, look: .reaction(.cheer, .center), frameIndex: 2, pointSize: 120),
                       "happy|cheer.center|2|120")
    }

    /// A loop that repeats a frame keys the repeat by its first occurrence;
    /// idle never does (its keys must not move).
    func test_repeatedFramesShareAKey_exceptOnTheIdlePath() {
        let attentive = BookwormSprites.frames(for: .awake, look: .pose(.attentive(.center))).frames
        XCTAssertEqual(BookwormRenderer.keyIndex(frames: attentive, look: .pose(.attentive(.center)), frameIndex: 2), 0)
        let idle = BookwormSprites.frames(for: .awake).frames
        XCTAssertEqual(BookwormRenderer.keyIndex(frames: idle, look: .idle, frameIndex: 2), 2)
    }

    /// Design §6.1: "the page's own key set is at most about 200 per size. A
    /// test pins it at ≤ 256." Measured at 216 when this plan was written.
    func test_thePagesKeySetStaysUnderTheBound() {
        var keys = Set<String>()
        for state in BookwormPoseSpriteTests.pageStates {
            for look in BookwormLook.reachable(for: state) {
                let frames = BookwormSprites.frames(for: state, look: look).frames
                for i in frames.indices {
                    keys.insert(BookwormRenderer.cacheKey(
                        state: state, look: look,
                        frameIndex: BookwormRenderer.keyIndex(frames: frames, look: look, frameIndex: i),
                        pointSize: 120))
                }
            }
        }
        XCTAssertLessThanOrEqual(keys.count, 256)
        XCTAssertGreaterThan(keys.count, 100, "the enumeration is not vacuous")
    }

    /// The menu bar's `curious(1…99)` keys alone can reach 297, so the wipe
    /// bound doubles in the same commit the page's poses arrive (design §6.1).
    func test_theWipeBoundDoubled() {
        XCTAssertEqual(BookwormRenderer.maxCacheEntries, 1024)
    }

    /// Z-P10: a beat plays under a key the bound above counted. The gaze folds
    /// to `.center` wherever the frames ignore it (a reaction that does not
    /// follow the eyes, or a state whose eyes must not move), and a beat the
    /// matrix forbids has no look at all. Without the fold, a cheer played
    /// while the pointer sits left of the worm would key as `cheer.left`,
    /// a key the ≤ 256 measurement never saw.
    func test_aBeatPlaysAsAReachableLook() {
        for state in BookwormPoseSpriteTests.pageStates {
            for reaction in BookwormReaction.allCases {
                for gaze in Gaze.allCases {
                    guard let look = BookwormLook.beat(reaction, for: state, gaze: gaze) else {
                        XCTAssertFalse(state.allows(reaction), "\(reaction) on \(state.spriteKey)")
                        continue
                    }
                    XCTAssertTrue(BookwormLook.reachable(for: state).contains(look),
                                  "\(reaction) \(gaze) on \(state.spriteKey)")
                }
            }
        }
        XCTAssertEqual(BookwormLook.beat(.cheer, for: .happy, gaze: .left), .reaction(.cheer, .center))
        XCTAssertEqual(BookwormLook.beat(.talk, for: .digesting, gaze: .right), .reaction(.talk, .center))
        XCTAssertNil(BookwormLook.beat(.talk, for: .error, gaze: .center))
    }

    func test_aLookImageIsCachedLikeAnyOther() {
        let a = BookwormRenderer.cachedImage(state: .awake, look: .pose(.attentive(.left)), frameIndex: 0, pointSize: 96)
        let b = BookwormRenderer.cachedImage(state: .awake, look: .pose(.attentive(.left)), frameIndex: 2, pointSize: 96)
        XCTAssertTrue(a === b, "frame 2 repeats frame 0 and shares its image")
    }

    // MARK: BookwormView's beat clock

    func test_reactionFrameIndex_playsOnceThenEnds() {
        let start = Date(timeIntervalSinceReferenceDate: 100)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start, startedAt: start, count: 3), 0)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.13), startedAt: start, count: 3), 1)
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.25), startedAt: start, count: 3), 2)
        XCTAssertNil(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(0.37), startedAt: start, count: 3))
        XCTAssertEqual(BookwormView.reactionFrameIndex(at: start.addingTimeInterval(-1), startedAt: start, count: 3), 0)
        XCTAssertNil(BookwormView.reactionFrameIndex(at: start, startedAt: start, count: 0))
    }

    /// Reduce Motion (§6.1): no gaze; the drop poses keep their frame 0
    /// because the armed-drop cue is a state, not a motion.
    func test_reduceMotionDropsTheGazeButKeepsTheArmedPose() {
        XCTAssertEqual(BookwormPose.attentive(.left).effective(for: .awake, reduceMotion: true), .idle)
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .awake, reduceMotion: true), .expectant(.left))
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .digesting, reduceMotion: false), .expectant(.center))
        XCTAssertEqual(BookwormPose.eager.effective(for: .sleeping(stage: 2), reduceMotion: false), .idle)
    }
}
