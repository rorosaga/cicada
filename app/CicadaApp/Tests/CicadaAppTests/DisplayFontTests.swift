import SwiftUI
import XCTest
@testable import CicadaApp

/// F1 R-FX12 — the display face is the system's SF Pro Display behind the
/// same API every caller already used. The owner, on the Instrument Serif page
/// titles (2026-09-23): "i dont like this font … Change it to something more
/// minimal."
final class DisplayFontTests: XCTestCase {
    func testRomanIsSemiboldSFAndItalicIsRegularSFItalic() {
        XCTAssertEqual(CicadaTheme.displayFont(size: 28),
                       Font.system(size: CicadaTheme.scaled(28), weight: .semibold, design: .default))
        XCTAssertEqual(CicadaTheme.displayFont(size: 22, italic: true),
                       Font.system(size: CicadaTheme.scaled(22), weight: .regular, design: .default).italic())
        XCTAssertEqual(CicadaTheme.displayFont(size: 12), CicadaTheme.displayFont(size: CicadaTheme.displayMinimumSize))
        XCTAssertEqual(CicadaTheme.quoteFont, CicadaTheme.font(size: 13, design: .serif).italic(),
                       "the provenance quote face is untouched")
    }

    func testTrackingIsSlightlyNegativeAndScalesWithTheFace() {
        XCTAssertEqual(CicadaTheme.displayTracking(size: 28), -0.02 * CicadaTheme.scaled(28), accuracy: 0.0001)
        XCTAssertLessThan(CicadaTheme.displayTracking(size: 28), 0)
        XCTAssertEqual(CicadaTheme.displayTracking(size: 12),
                       CicadaTheme.displayTracking(size: CicadaTheme.displayMinimumSize), accuracy: 0.0001)
    }
}
