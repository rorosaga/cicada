import XCTest
@testable import CicadaApp

/// G125 v3 Task 3: the study room is five 24×24 props authored in the same
/// `PixelGrid` encoding as the mascot, drawn through the same
/// `PixelRenderer`, in `DeskPalette`.
///
/// The contract these pin is the one a later art edit can silently break:
/// a grid that is no longer 24×24 (the renderer pads rather than traps, so a
/// short grid would just quietly lose its bottom rows), a character that is
/// not in the scene's palette (it renders as a transparent hole, not an
/// error), and — the one that matters most — a prop whose ink drifts out of
/// its documented ROW BAND. The bands are what `deskSceneLayout` places
/// against: the cushion's top row is the worm's baseline, the window's sill
/// row is where the wall meets the floor. A prop that grows upward by two
/// rows would push its own furniture into the worm's cells with no test
/// failing anywhere else.
final class DeskSceneSpritesTests: XCTestCase {

    /// Every grid the scene can draw, including BOTH lamp variants — `all`
    /// carries only the canonical one, and the dark shade is exactly the case
    /// a "renders at all" test would otherwise never visit.
    private var everyGrid: [(String, PixelGrid)] {
        DeskProp.allCases.map { ($0.rawValue, DeskSceneSprites.grid($0, lampLit: true)) }
            + [("lampDark", DeskSceneSprites.grid(.lamp, lampLit: false))]
    }

    private var allowed: Set<Character> {
        Set(DeskPalette.colors.keys).union([DeskPalette.transparent])
    }

    func testEveryPropIs24x24AndInTheDeskPalette() {
        for (name, grid) in everyGrid {
            XCTAssertEqual(grid.count, 24, "\(name) row count")
            for (r, row) in grid.enumerated() {
                XCTAssertEqual(row.count, 24, "\(name) row \(r) width")
                for ch in row where !allowed.contains(ch) {
                    XCTFail("\(name) row \(r): '\(ch)' is not a DeskPalette index")
                }
            }
        }
    }

    /// A prop that drifts out of its band on a later edit is caught here
    /// rather than by eye in the running app. `inkBounds` is the same helper
    /// `deskSceneLayout`'s own tests use to prove the pile never lands on
    /// painted furniture, so the two agree on what "the prop" means.
    func testEveryPropStaysInsideItsDocumentedRowBand() {
        for prop in DeskProp.allCases {
            for lit in [true, false] {
                let grid = DeskSceneSprites.grid(prop, lampLit: lit)
                guard let bounds = DeskSceneSprites.inkBounds(grid),
                      let band = DeskSceneSprites.rowBand[prop] else {
                    XCTFail("\(prop.rawValue) has no ink or no documented band")
                    continue
                }
                XCTAssertTrue(band.contains(bounds.rows.lowerBound),
                              "\(prop.rawValue) top row \(bounds.rows.lowerBound) outside \(band)")
                XCTAssertTrue(band.contains(bounds.rows.upperBound),
                              "\(prop.rawValue) bottom row \(bounds.rows.upperBound) outside \(band)")
            }
        }
    }

    /// Every prop's ink is authored flush to column 0 so a layer's scene
    /// column IS its `cellX` — the layout does no per-prop column arithmetic,
    /// which is what keeps `deskSceneLayout` readable as a floor plan.
    func testEveryPropIsAuthoredFlushToColumnZero() {
        for prop in DeskProp.allCases {
            let bounds = DeskSceneSprites.inkBounds(DeskSceneSprites.grid(prop, lampLit: true))
            XCTAssertEqual(bounds?.cols.lowerBound, 0, prop.rawValue)
        }
    }

    /// P11 — the lamp is the scene's ONE state bit, and the cheapest possible
    /// one: the two variants differ only where the shade is. Anything else
    /// changing between them would mean the schedule was moving furniture.
    func testLampVariantsDifferOnlyInTheShade() {
        let lit = DeskSceneSprites.grid(.lamp, lampLit: true)
        let dark = DeskSceneSprites.grid(.lamp, lampLit: false)
        XCTAssertNotEqual(lit, dark, "the lamp must actually change")
        for r in 0..<24 where !(4...8).contains(r) {
            XCTAssertEqual(lit[r], dark[r], "row \(r) is not the shade and must not move")
        }
        for r in 4...8 {
            XCTAssertEqual(Array(lit[r]).map { $0 == "." },
                           Array(dark[r]).map { $0 == "." },
                           "row \(r): the shade's SILHOUETTE is identical; only the fill differs")
        }
    }

    /// The window is the worked grid: night glass, a hand-drawn crescent, a
    /// static star field (R-A13 — idle is still, so the stars never twinkle)
    /// and a sill on the band's bottom row.
    func testWindowCarriesGlassAMoonStarsAndASill() {
        let w = DeskSceneSprites.window
        XCTAssertTrue(w.contains { $0.contains("k") }, "night glass")
        XCTAssertTrue(w.contains { $0.contains("m") }, "moonlight")
        XCTAssertTrue(w.contains { $0.contains("n") }, "moon terminator")
        XCTAssertEqual(w.filter { $0.contains("s") }.count, 4, "four static stars, one per pane")
        XCTAssertEqual(w[22], String(repeating: "d", count: 20) + "....", "the sill is the band's last row")
    }

    func testInkBoundsIsNilForAnEmptyGrid() {
        XCTAssertNil(DeskSceneSprites.inkBounds(Array(repeating: String(repeating: ".", count: 24), count: 24)))
    }
}
