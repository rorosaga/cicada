import CoreGraphics
import XCTest
@testable import CicadaApp

/// G125 v3 Task 3: the room is composed by ONE pure function on ONE cell
/// lattice, so the whole picture can be argued about without standing up a
/// view — the same way `bookPileLayout` and `studyRows` are tested.
///
/// The invariants here are the ones P12 and P10 name. P12: every prop renders
/// at the SAME snapped point size as the worm and is positioned by an integer
/// CELL count, because two pixel scales in one picture read as a bug at any
/// zoom and would break G130 R6's single `snappedPointSize` call. P10: the
/// page's one volume encoding is the REAL `BookPileView`, so the scene must
/// reserve a column for it that no painted furniture reaches into — a
/// decorative spine stack eighteen points from a real one would ask the
/// reader to tell a chart from wallpaper by taste.
final class DeskSceneLayoutTests: XCTestCase {

    // MARK: - The lattice

    /// At `uiScale == 1.0` the worm is 120 pt over 24 cells, so a cell is
    /// exactly 5 pt and the scene box is the lattice times that. Pinned as a
    /// number, not a formula, so a change to either constant is deliberate.
    func testCellAndSizeAtUnitScale() {
        let l = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        XCTAssertEqual(l.cell, 5)
        XCTAssertEqual(l.size.width, CGFloat(DeskScene.cols) * 5)
        XCTAssertEqual(l.size.height, CGFloat(DeskScene.rows) * 5)
    }

    /// G130 R6: the scene's point size is the worm's own snapped size, so the
    /// two never disagree about how big a pixel is. 1.4 is the app's ceiling
    /// (`ThemeStore.scaleRange`); 1.5 is included because the function is
    /// pure and must not misbehave past it.
    func testEveryScaleYieldsAWholeNumberOfPointsPerCell() {
        for scale in [0.8, 1.0, 1.2, 1.4, 1.5] {
            let l = deskSceneLayout(pointSize: 120, uiScale: scale)
            XCTAssertEqual(l.cell, BookwormRenderer.snappedPointSize(120 * CGFloat(scale)) / 24,
                           "uiScale \(scale): the scene's cell is the worm's snapped size over 24")
            XCTAssertEqual(l.cell, l.cell.rounded(), "uiScale \(scale): a cell is a whole number of points")
        }
    }

    // MARK: - Layers

    func testEveryPropAppearsExactlyOnceInStrictlyAscendingZOrder() {
        let l = deskSceneLayout()
        XCTAssertEqual(Set(l.layers.map(\.prop)), Set(DeskProp.allCases))
        XCTAssertEqual(l.layers.count, DeskProp.allCases.count)
        XCTAssertEqual(l.layers.map(\.z), l.layers.map(\.z).sorted())
        XCTAssertEqual(Set(l.layers.map(\.z)).count, l.layers.count, "z-order is strict, never a tie")
    }

    /// P12 in one assertion: an offset that is not an exact multiple of a
    /// cell is a prop drawn half a pixel off its own lattice.
    func testEveryOffsetIsAWholeNumberOfCells() {
        for scale in [0.8, 1.0, 1.4] {
            let l = deskSceneLayout(pointSize: 120, uiScale: scale)
            for layer in l.layers {
                XCTAssertEqual((CGFloat(layer.cellX) * l.cell).truncatingRemainder(dividingBy: l.cell), 0)
                XCTAssertEqual((CGFloat(layer.cellY) * l.cell).truncatingRemainder(dividingBy: l.cell), 0)
            }
            XCTAssertEqual(l.wormOrigin.x.truncatingRemainder(dividingBy: l.cell), 0, "uiScale \(scale)")
            XCTAssertEqual(l.wormOrigin.y.truncatingRemainder(dividingBy: l.cell), 0, "uiScale \(scale)")
            XCTAssertEqual(l.pileFrame.minX.truncatingRemainder(dividingBy: l.cell), 0, "uiScale \(scale)")
        }
    }

    /// Every 24×24 layer box — and the worm's, which is the same size —
    /// stays inside the scene rect at every scale. The check is scale-free by
    /// construction (everything is cells), which is exactly why it is worth
    /// asserting at three scales: a future absolute-point offset would break
    /// at two of them and pass at one.
    func testNoLayerBoxEscapesTheSceneRect() {
        for scale in [0.8, 1.0, 1.5] {
            let l = deskSceneLayout(pointSize: 120, uiScale: scale)
            for layer in l.layers {
                XCTAssertGreaterThanOrEqual(layer.cellX, 0, "\(layer.prop.rawValue) @\(scale)")
                XCTAssertGreaterThanOrEqual(layer.cellY, 0, "\(layer.prop.rawValue) @\(scale)")
                XCTAssertLessThanOrEqual(layer.cellX + 24, DeskScene.cols, "\(layer.prop.rawValue) @\(scale)")
                XCTAssertLessThanOrEqual(layer.cellY + 24, DeskScene.rows, "\(layer.prop.rawValue) @\(scale)")
            }
            let wormBox = CGRect(x: l.wormOrigin.x, y: l.wormOrigin.y, width: 24 * l.cell, height: 24 * l.cell)
            let scene = CGRect(origin: .zero, size: l.size)
            XCTAssertTrue(scene.contains(wormBox), "the worm @\(scale)")
            XCTAssertTrue(scene.contains(l.pileFrame), "the pile @\(scale)")
        }
    }

    /// R-A2 — the worm SITS on the cushion. The cushion's top ink row is the
    /// worm's baseline; if either the cushion art or the placement moves, the
    /// worm floats or sinks and only this assertion notices.
    func testTheWormsBaselineIsTheCushionsTopCell() {
        let l = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        guard let cushion = l.layers.first(where: { $0.prop == .cushion }),
              let ink = DeskSceneSprites.inkBounds(DeskSceneSprites.grid(.cushion, lampLit: true)) else {
            return XCTFail("no cushion layer")
        }
        // Grid row r of a layer at cellY sits at scene cell `cellY + 23 - r`.
        let cushionTopCell = cushion.cellY + 23 - ink.rows.lowerBound
        XCTAssertEqual(l.wormOrigin.y, CGFloat(cushionTopCell) * l.cell)
    }

    /// P10 — the reserved pile column touches no painted furniture. Asserted
    /// against each prop's real INK box, not its 24×24 grid: the grids overlap
    /// each other freely (that is what z-order is for), and it is the visible
    /// paint that would collide with a real chart.
    func testThePileColumnNeverOverlapsPaintedFurniture() {
        let l = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        for layer in l.layers {
            for lit in [true, false] {
                guard let ink = DeskSceneSprites.inkBounds(DeskSceneSprites.grid(layer.prop, lampLit: lit)) else {
                    continue
                }
                let box = CGRect(
                    x: CGFloat(layer.cellX + ink.cols.lowerBound) * l.cell,
                    y: CGFloat(layer.cellY + 23 - ink.rows.upperBound) * l.cell,
                    width: CGFloat(ink.cols.count) * l.cell,
                    height: CGFloat(ink.rows.count) * l.cell)
                XCTAssertFalse(box.intersects(l.pileFrame),
                               "\(layer.prop.rawValue) ink \(box) sits under the pile \(l.pileFrame)")
            }
        }
    }

    /// The pile is the REAL `BookPileView`, whose widest spine is
    /// `BookPileView.maxSpineWidth`. A reserved column narrower than that
    /// would push a full-width spine out of the scene — the geometry reason
    /// the lattice is as wide as it is, recorded as an assertion so nobody
    /// "tidies" the scene narrower.
    func testThePileColumnFitsAFullWidthSpine() {
        let l = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        XCTAssertGreaterThanOrEqual(l.pileFrame.width, 150)
    }
}
