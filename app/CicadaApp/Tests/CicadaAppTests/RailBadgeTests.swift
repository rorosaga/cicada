import XCTest
@testable import CicadaApp

final class RailBadgeTests: XCTestCase {
    /// Owner 2026-11-06: 659 on the Home icon covered it; past 99 the rail reads "99+".
    func testCountCapsAtNinetyNinePlus() {
        XCTAssertEqual(RailBadge.text(6), "6")
        XCTAssertEqual(RailBadge.text(99), "99")
        XCTAssertEqual(RailBadge.text(100), "99+")
        XCTAssertEqual(RailBadge.text(659), "99+")
    }
}
