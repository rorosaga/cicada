import SwiftUI
import XCTest
@testable import CicadaApp

/// G125 v3 Task 7 — the page's two-column arrangement, as a pure function of
/// the width it is given. The reflow boundary is NAMED here rather than left
/// to a `>` buried in a `body`, so "what happens at exactly 1000 pt" has an
/// answer a reader can check.
final class SleepLayoutTests: XCTestCase {

    func test_sleepLayout_isTwoColumnAtAComfortableWidth() {
        XCTAssertTrue(sleepLayout(width: 1200).isTwoColumn)
    }

    func test_sleepLayout_stacksBelowTheBoundary() {
        XCTAssertFalse(sleepLayout(width: 999).isTwoColumn)
        XCTAssertFalse(sleepLayout(width: 640).isTwoColumn)
    }

    /// The boundary is inclusive, and it is asserted rather than guessed: a
    /// reflow that happens at 1000 in one build and 1001 in the next is the
    /// kind of drift only a test at the exact value catches.
    func test_sleepLayout_theBoundaryItselfIsTwoColumn() {
        XCTAssertEqual(SleepLayout.twoColumnMinWidth, 1000)
        XCTAssertTrue(sleepLayout(width: SleepLayout.twoColumnMinWidth).isTwoColumn)
    }

    /// `maxContentWidth` is part of the layout, not a leftover literal in the
    /// body: the stacked page keeps the 760 pt column it has always had, and
    /// the two-column page needs a cap no two columns could fit inside.
    func test_sleepLayout_carriesTheContentCapForBothArrangements() {
        XCTAssertEqual(sleepLayout(width: 999).maxContentWidth, 760)
        XCTAssertGreaterThan(sleepLayout(width: 1200).maxContentWidth, 1000)
    }

    /// Stacked means one column of full width — a fraction below 1 there would
    /// silently narrow the hero on a small window.
    func test_sleepLayout_leftFractionIsTheWholeWidthWhenStacked() {
        XCTAssertEqual(sleepLayout(width: 999).leftFraction, 1.0, accuracy: 1e-9)
    }

    /// Roughly two thirds — the hero, the room and the queue are the page's
    /// subject; memory sources and past cycles are its margin.
    func test_sleepLayout_leftColumnIsTheWiderOneWhenSideBySide() {
        let fraction = sleepLayout(width: 1200).leftFraction
        XCTAssertGreaterThan(fraction, 0.55)
        XCTAssertLessThan(fraction, 0.75)
    }

    /// Stacked means there is nothing to divide — `nil`, so a caller cannot
    /// accidentally pin a one-column page to two thirds of itself.
    func test_leftColumnWidth_isNilWhenStacked() {
        XCTAssertNil(sleepLayout(width: 900).leftColumnWidth(available: 900, padding: 24, gutter: 16))
    }

    /// The two columns plus the gutter fit inside the content cap, and the left
    /// one lands near the 760 pt the single column has always had — the point
    /// of the wider cap.
    func test_leftColumnWidth_fitsInsideTheCapAndKeepsTheOldColumnWidth() {
        let layout = sleepLayout(width: 1400)
        guard let left = layout.leftColumnWidth(available: 1400, padding: 24, gutter: 16) else {
            return XCTFail("a two-column layout must have a left width")
        }
        let content = layout.maxContentWidth - 48 - 16
        XCTAssertLessThan(left, content)
        XCTAssertEqual(left, content * layout.leftFraction, accuracy: 0.001)
        XCTAssertGreaterThan(left, 700)
    }

    /// A width of zero arrives on the first layout pass of a freshly opened
    /// window; it must not read as "narrow, therefore stacked and then reflow
    /// a frame later" — but it must never be two columns either, because a
    /// zero-width two-column split would divide a zero.
    func test_sleepLayout_zeroWidthStacks() {
        XCTAssertFalse(sleepLayout(width: 0).isTwoColumn)
        XCTAssertEqual(sleepLayout(width: 0).maxContentWidth, 760)
    }
}
