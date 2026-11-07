import XCTest
@testable import CicadaApp

/// The band's two labels over the track — "You, today" and the next milestone's words — never collide (owner
/// 2026-10-28: "You, todayFibreglass the hull"). Pure: `BandLayout.nextLabel` with a fixed-width measure (6 units a
/// character), so the geometry is exact.
final class ProjectBandLabelTests: XCTestCase {
    private let gap: CGFloat = 8
    private let width: CGFloat = 1000
    private func measure(_ s: String) -> CGFloat { CGFloat(s.count) * 6 }
    private let full = "Fibreglass the hull · in 11 days"   // 32 characters, 192 units
    private let shortName = "Fibreglass the hull"                // 19 characters, 114 units

    private func label(today: CGFloat, next: CGFloat, width: CGFloat? = nil) -> BandLayout.LabelSpan? {
        BandLayout.nextLabel(todayX: today, next: .init(x: next, label: full), name: shortName, width: width ?? self.width,
                             gap: gap, measure: measure)
    }

    /// The two extents never overlap, with the gap, and the next label stays inside the band.
    private func assertClear(_ l: BandLayout.LabelSpan, today: CGFloat, width: CGFloat? = nil,
                             file: StaticString = #filePath, line: UInt = #line) {
        let w = measure(l.text) / 2
        let t = measure(Copy.Projects.youToday) / 2
        XCTAssertTrue(l.center + w < today - t - gap || l.center - w > today + t + gap,
                      "collides with You, today: \(l)", file: file, line: line)
        XCTAssertGreaterThanOrEqual(l.center - w, 0, file: file, line: line)
        XCTAssertLessThanOrEqual(l.center + w, width ?? self.width, file: file, line: line)
    }

    func testFarApartTheWordsSitCentredOnTheDiamond() throws {
        let l = try XCTUnwrap(label(today: 300, next: 700))
        XCTAssertEqual(l, .init(text: full, center: 700))
    }

    /// The owner's case: the next target 11 days on, about 110 units right of today.
    func testCloseOnTheRightTheWordsArePushedClearAndStillReachTheirDiamond() throws {
        let l = try XCTUnwrap(label(today: 600, next: 710))
        XCTAssertEqual(l.text, full)
        assertClear(l, today: 600)
        XCTAssertLessThanOrEqual(l.center - measure(full) / 2, 710, "the words still reach over their diamond")
    }

    func testNearTheBandsEndTheNameAloneSitsThere() throws {
        // Pushed clear, the full words would run past the band's end; the name alone fits and reaches its diamond.
        let l = try XCTUnwrap(label(today: 700, next: 760, width: 900))
        XCTAssertEqual(l.text, shortName)
        assertClear(l, today: 700, width: 900)
        XCTAssertLessThanOrEqual(l.center - measure(l.text) / 2, 760)
    }

    func testOnTopOfTodayTheLabelIsLeftToTheDiamondsHoverWords() {
        XCTAssertNil(label(today: 600, next: 602))
    }

    func testLeftOfTodayAndAtTheBandsEnds() throws {
        let left = try XCTUnwrap(label(today: 600, next: 480))
        assertClear(left, today: 600)
        let end = try XCTUnwrap(label(today: 300, next: 995))
        XCTAssertEqual(end.center + measure(end.text) / 2, width, "pulled inside the band, never clipped")
    }

    /// The class, not the case: wherever the next target falls, whatever is drawn never collides.
    func testNoPositionEverCollides() {
        for today in stride(from: CGFloat(40), through: 960, by: 40) {
            for next in stride(from: CGFloat(0), through: width, by: 5) {
                if let l = label(today: today, next: next) { assertClear(l, today: today) }
            }
        }
    }

    func testNoNextMilestoneNoLabel() {
        XCTAssertNil(BandLayout.nextLabel(todayX: 300, next: nil, name: nil, width: width, gap: gap, measure: measure))
    }
}
