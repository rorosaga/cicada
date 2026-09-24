import XCTest
@testable import CicadaApp

/// R-DG12 — the canvas and the entity column, pure. Page widths are what `ShellReaderHost` gives the page:
/// the content width minus the Reader's `ColumnLayout.readerWidth` (420 at 1440, 360 at 1200).
final class GraphColumnsTests: XCTestCase {
    private func plan(_ page: CGFloat, reader: Bool, scale: CGFloat = 1, open: Bool = true) -> GraphColumns.Plan {
        GraphColumns.plan(pageWidth: page, scale: scale, entityOpen: open, readerOpen: reader)
    }

    /// The approved mock at 1440: 560 alone; 480 beside the Reader with the rail; 440 with the labelled sidebar.
    func testTheMocksWidthsAt1440() {
        let rows: [(CGFloat, Bool, CGFloat)] = [(1384, false, 560), (1232, false, 560), (964, true, 480), (812, true, 440)]
        for (page, reader, entity) in rows {
            let p = plan(page, reader: reader)
            XCTAssertEqual(p.entity, entity, "page \(page) reader \(reader)")
            XCTAssertEqual(p.canvas, page - entity)
        }
    }

    func testAt1200TheFloorHolds() {
        let rows: [(CGFloat, Bool, CGFloat)] = [(1144, false, 560), (992, false, 496), (784, true, 440), (632, true, 440)]
        for (page, reader, entity) in rows {
            XCTAssertEqual(plan(page, reader: reader).entity, entity, "page \(page) reader \(reader)")
        }
    }

    func testClosedTheCanvasIsThePage() {
        XCTAssertEqual(plan(1384, reader: false, open: false), GraphColumns.Plan(canvas: 1384, entity: 0))
    }

    /// DR-70 — units: at 1.4× a 1440 window's page (1361.6 pt) is 972.6 units, half of which is 486.3 units.
    func testZoomWorksInUnits() {
        let p = plan(1361.6, reader: false, scale: 1.4)
        XCTAssertEqual(p.entity, 681)
        XCTAssertEqual(p.canvas, 680.6, accuracy: 0.001)
    }

    /// DR-31 — a page narrower than the floor gives the column everything and nothing overflows.
    func testANarrowPageNeverOverflows() {
        XCTAssertEqual(plan(300, reader: true), GraphColumns.Plan(canvas: 0, entity: 300))
    }

    func testEveryPlanSumsToThePage() {
        for scale: CGFloat in [0.8, 1.0, 1.2, 1.4] {
            for page in stride(from: CGFloat(0), through: 2400, by: 37) {
                for reader in [false, true] {
                    let p = plan(page, reader: reader, scale: scale)
                    XCTAssertEqual(p.canvas + p.entity, page, accuracy: 0.001)
                    XCTAssertGreaterThanOrEqual(p.canvas, 0)
                }
            }
        }
    }
}
