import XCTest
@testable import CicadaApp

/// Owner 2026-11-23: every chat glides back to its newest message, "fast but smooth", faster the further it is.
@MainActor
final class JumpToLatestTests: XCTestCase {
    func testALongerWayTakesLongerButMovesFaster() {
        let near = CicadaMotion.jumpToLatestDuration(distance: 2_000)
        let far = CicadaMotion.jumpToLatestDuration(distance: 20_000)
        XCTAssertGreaterThan(far, near)
        XCTAssertGreaterThan(20_000 / far, 2_000 / near, "points per second grow with the distance")
    }

    func testTheGlideStaysUnderTheMotionCeiling() {
        for d in [0, 500, 5_000, 50_000, 5_000_000] as [CGFloat] {
            XCTAssertLessThanOrEqual(CicadaMotion.jumpToLatestDuration(distance: d), CicadaMotion.maxDuration)
            XCTAssertGreaterThan(CicadaMotion.jumpToLatestDuration(distance: d), 0)
        }
    }

    func testTheButtonShowsOnlyWellAboveTheNewestMessage() {
        XCTAssertFalse(JumpToLatest.isAway(anchorY: nil, visibleBottom: 0))
        XCTAssertFalse(JumpToLatest.isAway(anchorY: 1_000, visibleBottom: 1_000))
        XCTAssertFalse(JumpToLatest.isAway(anchorY: 1_000, visibleBottom: 1_000 - CicadaTheme.scaled(JumpToLatest.threshold)))
        XCTAssertTrue(JumpToLatest.isAway(anchorY: 1_000, visibleBottom: 500))
    }
}
