import XCTest
@testable import CicadaApp

/// R-HS2 — Home's band is the D-Home mock: the painted hero, 120 pt, the meadow line in view,
/// and nothing over it (DR-13, DR-50: text never sits on paint).
final class HomeBandLayoutTests: XCTestCase {
    func testTheBandIsTheMocksHeightAndFade() {
        XCTAssertEqual(HomeBandLayout.bandHeight, 120)
        XCTAssertEqual(HomeBandLayout.focusY, 0.63, accuracy: 0.0001, "object-position: center 63%")
        XCTAssertEqual(HomeBandLayout.fadeStart, 0.4, accuracy: 0.0001, "mask: #000 40% → transparent")
    }

    /// The painting is 1200 × 700 pt (2400 × 1400 px at 2×). Filled into the band, it moves exactly as
    /// CSS `object-fit: cover; object-position: center 63%` moves it: the painting's 63 % line meets
    /// the band's 63 % line, i.e. the centred painting shifts up by 13 % of its overflow — and so never
    /// far enough for the band to show past its edge.
    func testTheImageOffsetIsObjectPositionSixtyThreeAndNeverUncoversTheBand() {
        let hero = CGSize(width: 1200, height: 700)
        // 1000 wide: filled 583.33 tall, overflow 463.33, × 0.13.
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 1000, height: 120)),
                       -60.2333, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 400, height: 120)),
                       -14.7333, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 3000, height: 120)),
                       -211.9, accuracy: 0.001)
        // A band the filled painting exactly covers: no overflow, no shift, never a gap.
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 100, height: 300)),
                       0, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: .zero, bandSize: CGSize(width: 100, height: 120)), 0)
        for width in stride(from: CGFloat(320), through: 2400, by: 40) {
            for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
                let band = CGSize(width: width, height: HomeBandLayout.bandHeight * scale)
                let fill = max(band.width / hero.width, band.height / hero.height)
                let slack = (hero.height * fill - band.height) / 2
                let offset = HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: band)
                XCTAssertLessThanOrEqual(abs(offset), slack + 0.001, "width \(width) scale \(scale)")
            }
        }
    }

    /// DR-13 / DR-50 — the band is paint only, and nothing is drawn over it: the headline is the
    /// next row down, so no `Text(` lives in the band's file and Home stacks rather than overlays.
    func testNoWordIsDrawnOnThePaint() throws {
        let files = try ThemeTokenTests.swiftSources()
        let band = try XCTUnwrap(files.first { $0.path.hasSuffix("Views/Meadow/HomeHeroBand.swift") })
        let bandText = try String(contentsOf: band, encoding: .utf8)
        XCTAssertFalse(bandText.contains("Text("), "the band carries no word (DR-13)")
        XCTAssertFalse(bandText.contains("DriftingCloud("), "the hero's clouds are painted (R-HS2)")
        let home = try XCTUnwrap(files.first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let homeText = try String(contentsOf: home, encoding: .utf8)
        XCTAssertFalse(homeText.contains("ZStack"), "nothing on Home is layered over the band")
        let bandLine = try XCTUnwrap(homeText.range(of: "HomeHeroBand()"))
        let titleLine = try XCTUnwrap(homeText.range(of: "PageTitle(Copy.homeHeadline)"))
        XCTAssertLessThan(bandLine.lowerBound, titleLine.lowerBound, "the headline is the row under the band")
    }
}
