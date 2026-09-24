import XCTest
@testable import CicadaApp

/// DR-40 / DR-44 / DR-34 — the controls' fixed numbers, read from one place.
final class ControlVocabularyTests: XCTestCase {
    func testTheNeutralButtonIsTwentyEightOrThirtyTwoAndDisabledIsFortyFivePercent() {
        XCTAssertEqual(NeutralButton.Size.compact.height, 28)
        XCTAssertEqual(NeutralButton.Size.regular.height, 32)
        XCTAssertEqual(NeutralButton.disabledOpacity, 0.45, "DR-41")
        XCTAssertEqual(TextButton.height, 32)
    }

    func testTheOnePillIsEighteenTall() {
        XCTAssertEqual(Tag.height, 18)
        XCTAssertEqual(Tag.dotSize, 6)
    }

    /// DR-34 / §5.5 — each row role has one height.
    func testEachRowRoleHasOneHeight() {
        XCTAssertEqual(RowMetrics.oneLine, 36)
        XCTAssertEqual(RowMetrics.twoLine, 56)
        XCTAssertEqual(RowMetrics.titleOnly, 36)
        XCTAssertEqual(RowMetrics.option, 48)
        XCTAssertEqual(RowMetrics.twoLineGap, 2)
        XCTAssertEqual(RowMetrics.optionGap, 4)
    }
}
