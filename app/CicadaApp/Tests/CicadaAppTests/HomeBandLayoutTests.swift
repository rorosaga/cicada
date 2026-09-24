import XCTest
@testable import CicadaApp

/// F-09 / R-HO6 — Home's band is `PaintedScene`'s `.hero` framing: its height here, its crop and fade in
/// `SceneGeometry`, and nothing over it (DR-13, DR-50: text never sits on paint).
final class HomeBandLayoutTests: XCTestCase {
    func testTheBandFadesBelowTheMeadowLine() {
        XCTAssertEqual(HomeBandLayout.bandHeight, 208, "F-09 (R-HO6)")
        XCTAssertEqual(SceneGeometry.bandFadeStart, 0.72, accuracy: 0.0001)
        XCTAssertGreaterThan(SceneGeometry.bandFadeStart, SceneGeometry.bandHorizon,
                             "the fade starts below the meadow line (ART_DIRECTION §3's note)")
    }

    func testNoWordIsDrawnOnThePaint() throws {
        let files = try ThemeTokenTests.swiftSources()
        func text(_ suffix: String) throws -> String {
            try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }, suffix), encoding: .utf8)
        }
        XCTAssertTrue(try text("Views/Meadow/HomeHeroBand.swift").contains("PaintedScene(.hero(band:"))
        for suffix in ["Views/Meadow/HomeHeroBand.swift", "Views/Meadow/PaintedScene.swift",
                       "Views/Meadow/SceneFraming.swift", "Views/Meadow/SceneMotion.swift"] {
            XCTAssertFalse(try text(suffix).contains("Text("), "\(suffix) carries no word (DR-13)")
        }
        let home = try text("Views/Home/HomeView.swift")
        XCTAssertFalse(home.contains("ZStack"), "nothing on Home is layered over the band")
        let band = try XCTUnwrap(home.range(of: "HomeHeroBand()"))
        let title = try XCTUnwrap(home.range(of: "PageTitle(Copy.homeHeadline)"))
        XCTAssertLessThan(band.lowerBound, title.lowerBound, "the headline is the row under the band")
    }
}
