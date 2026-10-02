import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 — three horizontal poses over the room, the worm's own ink
/// span as the dead zone, one cell of hysteresis on both edges.
final class GazeTests: XCTestCase {

    private let layout = deskSceneLayout(uiScale: 1.0)

    private var left: CGFloat { CGFloat(DeskHotspots.wormCols.lowerBound) * layout.cell }
    private var right: CGFloat { CGFloat(DeskHotspots.wormCols.upperBound + 1) * layout.cell }
    private var center: CGFloat { (left + right) / 2 }

    func test_threePosesAcrossTheRoom() {
        XCTAssertEqual(gazeFor(pointerX: nil, layout: layout, previous: .left, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: left - layout.cell, layout: layout, previous: .center, state: .awake), .left)
        XCTAssertEqual(gazeFor(pointerX: center, layout: layout, previous: .center, state: .awake), .center)
        XCTAssertEqual(gazeFor(pointerX: right + layout.cell, layout: layout, previous: .center, state: .awake), .right)
    }

    /// §6.4 — sleeping eyes stay shut, red pupils and a chewing worm look ahead.
    func test_suppressedStatesAlwaysLookAhead() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            XCTAssertEqual(gazeFor(pointerX: 10, layout: layout, previous: .left, state: state), .center)
        }
    }

    /// A sweep back and forth across a boundary changes the gaze at most once.
    func test_aBoundarySweepChangesTheGazeOnce() {
        for (edge, outward) in [(left, CGFloat(-1)), (right, 1)] {
            var gaze = gazeFor(pointerX: center, layout: layout, previous: .center, state: .reading)
            var changes = 0
            for step in 0..<20 {
                let x = edge + (step.isMultiple(of: 2) ? outward : -outward) * (layout.cell / 2)   // half a cell around the edge
                let next = gazeFor(pointerX: x, layout: layout, previous: gaze, state: .reading)
                if next != gaze { changes += 1 }
                gaze = next
            }
            XCTAssertEqual(changes, 1, "edge \(edge)")
        }
    }

    func test_leavingASideTakesAWholeCell() {
        for step in 8...14 {
            let layout = deskSceneLayout(uiScale: Double(step) / 10)
            let left = CGFloat(DeskHotspots.wormCols.lowerBound) * layout.cell
            let right = CGFloat(DeskHotspots.wormCols.upperBound + 1) * layout.cell
            XCTAssertEqual(gazeFor(pointerX: left + layout.cell - 0.5, layout: layout, previous: .left, state: .awake), .left)
            XCTAssertEqual(gazeFor(pointerX: left + layout.cell, layout: layout, previous: .left, state: .awake), .center)
            XCTAssertEqual(gazeFor(pointerX: right - layout.cell, layout: layout, previous: .right, state: .awake), .right)
            XCTAssertEqual(gazeFor(pointerX: right - layout.cell - 0.5, layout: layout, previous: .right, state: .awake), .center)
        }
    }
}
