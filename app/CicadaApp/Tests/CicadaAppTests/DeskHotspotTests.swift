import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 / R-Z8 — the hotspot layer is derived from the pure layout, in
/// whole cells, so it can never drift from the art it sits on.
final class DeskHotspotTests: XCTestCase {

    private var scales: [Double] { (8...14).map { Double($0) / 10 } }

    func test_everyHotspotIsWholeCellsInsideTheScene() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let spots = deskHotspots(layout)
            XCTAssertEqual(Set(spots.keys), Set(DeskHotspot.allCases))
            for (spot, rect) in spots {
                for v in [rect.minX, rect.minY, rect.width, rect.height] {
                    XCTAssertEqual(v.truncatingRemainder(dividingBy: layout.cell), 0, "\(spot) @\(scale)")
                }
                XCTAssertTrue(CGRect(origin: .zero, size: layout.size).contains(rect), "\(spot) @\(scale)")
            }
        }
    }

    /// Pairwise disjoint — a pointer is over one thing or none; the window
    /// stops where the worm starts.
    func test_hotspotsNeverOverlap() {
        for scale in scales {
            let spots = Array(deskHotspots(deskSceneLayout(pointSize: 120, uiScale: scale)).values)
            for i in spots.indices { for j in spots.indices where j > i {
                XCTAssertTrue(spots[i].intersection(spots[j]).isEmpty, "@\(scale)")
            } }
        }
    }

    /// P10 — the lamp and the window never reach into the real pile's column.
    func test_theLampAndTheWindowStayOutOfThePileColumn() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let spots = deskHotspots(layout)
            for spot in [DeskHotspot.lamp, .window] {
                XCTAssertTrue(spots[spot]!.intersection(layout.pileFrame).isEmpty, "\(spot) @\(scale)")
            }
        }
    }

    func test_theEyesAreInsideTheWorm() {
        for scale in scales {
            let layout = deskSceneLayout(pointSize: 120, uiScale: scale)
            let eye = CGPoint(x: (CGFloat(DeskHotspots.eyeCell.col) + 0.5) * layout.cell,
                              y: (CGFloat(DeskHotspots.eyeCell.row) + 0.5) * layout.cell)
            XCTAssertTrue(deskHotspots(layout)[.worm]!.contains(eye), "@\(scale)")
        }
    }

    /// The numbers the design names, at 5 pt per cell.
    func test_theCellsTheDesignNames() {
        let spots = deskHotspots(deskSceneLayout(pointSize: 120, uiScale: 1.0))
        XCTAssertEqual(spots[.worm], CGRect(x: 150, y: 20, width: 100, height: 120), "cols 30–49 × rows 4–27")
        XCTAssertEqual(spots[.lamp], CGRect(x: 0, y: 0, width: 50, height: 100), "the lamp's ink")
        XCTAssertEqual(spots[.window], CGRect(x: 100, y: 40, width: 50, height: 80), "glass cols 20–29 × rows 8–23")
    }

    /// The window's glass rectangle is named once, and today's worked grid
    /// agrees with it: every non-frame cell lies inside it.
    func test_theGlassRectangleMatchesTheWorkedGrid() {
        let glass = DeskSceneSprites.windowGlass
        for (r, row) in DeskSceneSprites.window.enumerated() {
            for (c, ch) in row.enumerated() where ch != "." && ch != "f" && ch != "d" {
                XCTAssertTrue(glass.rows.contains(r) && glass.cols.contains(c), "(\(r),\(c)) '\(ch)'")
            }
        }
    }

    func test_sceneBottomLeadingFlipsY() {
        let layout = deskSceneLayout(pointSize: 120, uiScale: 1.0)
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 200, y: 70), in: layout), CGPoint(x: 200, y: 70))
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 10, y: 0), in: layout), CGPoint(x: 10, y: 140))
    }
}
