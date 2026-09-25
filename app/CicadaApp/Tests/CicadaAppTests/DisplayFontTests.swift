import SwiftUI
import XCTest
@testable import CicadaApp

/// F1 R-FX12, DR-15 — the display face is the system's SF Pro Display behind the
/// same API every caller already used. The owner, on the Instrument Serif page
/// titles (2026-09-23): "i dont like this font … Change it to something more
/// minimal."
final class DisplayFontTests: XCTestCase {
    override func tearDown() { CicadaTheme.uiScale = 1.0; super.tearDown() }

    func testRomanIsSemiboldSFAndItalicIsRegularSFItalic() {
        XCTAssertEqual(CicadaTheme.displayFont(size: 28),
                       Font.system(size: CicadaTheme.scaled(28), weight: .semibold, design: .default))
        XCTAssertEqual(CicadaTheme.displayFont(size: 22, italic: true),
                       Font.system(size: CicadaTheme.scaled(22), weight: .regular, design: .default).italic())
        XCTAssertEqual(CicadaTheme.displayFont(size: 12), CicadaTheme.displayFont(size: CicadaTheme.displayMinimumSize))
        XCTAssertEqual(CicadaTheme.displayMinimumSize, 20, "DR-15")
    }

    /// DR-18 — every word a person or an agent said passes through one door: SF 15 regular,
    /// not italic, not serif. New York left with Instrument Serif (§9, 2026-09-23).
    func testTheQuoteIsSFFifteen() {
        XCTAssertEqual(CicadaTheme.quoteFont, CicadaTheme.font(size: 15))
        XCTAssertEqual(CicadaTheme.quoteFont(size: 12), CicadaTheme.font(size: 12))
    }

    /// DR-15 — −0.3 at 20 pt, −0.4 at 22 pt and above, scaled with the face.
    func testTrackingIsTheRulesLadder() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(CicadaTheme.displayTracking(size: 20), -0.3, accuracy: 0.0001)
        XCTAssertEqual(CicadaTheme.displayTracking(size: 22), -0.4, accuracy: 0.0001)
        XCTAssertEqual(CicadaTheme.displayTracking(size: 30), -0.4, accuracy: 0.0001)
        XCTAssertEqual(CicadaTheme.displayTracking(size: 12), CicadaTheme.displayTracking(size: 20), accuracy: 0.0001)
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(CicadaTheme.displayTracking(size: 28), -0.56, accuracy: 0.0001)
    }
}
