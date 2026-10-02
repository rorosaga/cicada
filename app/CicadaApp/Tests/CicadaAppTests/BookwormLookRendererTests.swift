import XCTest
@testable import CicadaApp

@MainActor
final class BookwormLookRendererTests: XCTestCase {
    func testDecodedPixelsAndDistinctRoomRectsStayBounded() throws {
        var pixels = 0
        for name in SpriteTestAssets.sheetNames {
            let sheet = try SpriteTestAssets.sheet(name)
            pixels += sheet.image.width * sheet.image.height
            if name.hasPrefix("bookworm-") && name != "bookworm-small" {
                XCTAssertLessThanOrEqual(Set(sheet.rectIndex).count, 1024, name)
            }
        }
        XCTAssertLessThanOrEqual(pixels, 8_388_608)
        XCTAssertEqual(BookwormRenderer.maxCacheEntries, 1024)
    }

    func testOnceClockUsesTheRealPerkDurations() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-awake")
        let clip = try SpriteTestAssets.clip(sheet, "perk.center")
        let start = SpriteClock.origin
        XCTAssertEqual(clip.onceStep(at: start, startedAt: start, profile: .full), 0)
        XCTAssertEqual(clip.onceStep(at: start.addingTimeInterval(clip.seconds[0] + 0.0005), startedAt: start, profile: .full), 1)
        XCTAssertNil(clip.onceStep(at: start.addingTimeInterval(clip.total), startedAt: start, profile: .full))
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

    /// Reduce Motion (§6.1): no gaze; the drop poses keep their frame 0
    /// because the armed-drop cue is a state, not a motion.
    func test_reduceMotionDropsTheGazeButKeepsTheArmedPose() {
        XCTAssertEqual(BookwormPose.attentive(.left).effective(for: .awake, reduceMotion: true), .idle)
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .awake, reduceMotion: true), .expectant(.left))
        XCTAssertEqual(BookwormPose.expectant(.left).effective(for: .digesting, reduceMotion: false), .expectant(.center))
        XCTAssertEqual(BookwormPose.eager.effective(for: .sleeping(stage: 2), reduceMotion: false), .idle)
    }
}
