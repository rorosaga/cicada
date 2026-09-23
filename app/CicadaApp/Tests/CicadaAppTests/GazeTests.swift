import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 — three horizontal poses over the room, the worm's own ink
/// span as the dead zone, one cell of hysteresis on both edges.
final class GazeTests: XCTestCase {

    private let layout = deskSceneLayout(pointSize: 120, uiScale: 1.0)   // 5 pt cells: worm 150…250

    func test_threePosesAcrossTheRoom() {
        XCTAssertEqual(gazeFor(pointerX: nil, layout: layout, previous: .left, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 100, layout: layout, previous: .center, state: .awake), .left)
        XCTAssertEqual(gazeFor(pointerX: 200, layout: layout, previous: .center, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 300, layout: layout, previous: .center, state: .awake), .right)
    }

    /// §6.4 — sleeping eyes stay shut, red pupils and a chewing worm look ahead.
    func test_suppressedStatesAlwaysLookAhead() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            XCTAssertEqual(gazeFor(pointerX: 10, layout: layout, previous: .left, state: state), .center)
        }
    }

    /// A sweep back and forth across a boundary changes the gaze at most once.
    func test_aBoundarySweepChangesTheGazeOnce() {
        for (edge, outward) in [(CGFloat(150), CGFloat(-1)), (250, 1)] {
            var gaze = gazeFor(pointerX: 200, layout: layout, previous: .center, state: .reading)
            var changes = 0
            for step in 0..<20 {
                let x = edge + (step.isMultiple(of: 2) ? outward : -outward) * 2   // ±2 pt around the edge
                let next = gazeFor(pointerX: x, layout: layout, previous: gaze, state: .reading)
                if next != gaze { changes += 1 }
                gaze = next
            }
            XCTAssertEqual(changes, 1, "edge \(edge)")
        }
    }

    func test_leavingASideTakesAWholeCell() {
        XCTAssertEqual(gazeFor(pointerX: 153, layout: layout, previous: .left, state: .awake), .left)
        XCTAssertEqual(gazeFor(pointerX: 156, layout: layout, previous: .left, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: 246, layout: layout, previous: .right, state: .awake), .right)
        XCTAssertEqual(gazeFor(pointerX: 244, layout: layout, previous: .right, state: .awake), .center)
    }
}
