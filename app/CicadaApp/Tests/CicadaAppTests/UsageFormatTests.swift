import XCTest
@testable import CicadaApp

/// G124 (2026-09-03 ruling): `UsageFormat.tokens`, `.usd` and `.costLine`
/// are gone with the prices and token counts they formatted — only the
/// count/percent/duration/harness formatters remain.
final class UsageFormatTests: XCTestCase {
    // MARK: G68 §2.5 — harness numbers go through UsageFormat too

    func testCount() {
        XCTAssertEqual(UsageFormat.count(0), "0")
        XCTAssertEqual(UsageFormat.count(999), "999")
        XCTAssertEqual(UsageFormat.count(1_284), "1,284")
        XCTAssertEqual(UsageFormat.count(1_284_000), "1,284,000")
    }

    func testPercent() {
        XCTAssertEqual(UsageFormat.percent(nil), "—")
        XCTAssertEqual(UsageFormat.percent(0), "0%")
        XCTAssertEqual(UsageFormat.percent(43.7), "44%")
    }

    func testDuration() {
        XCTAssertEqual(UsageFormat.duration(ms: nil), "—")
        XCTAssertEqual(UsageFormat.duration(ms: 20_000), "<1m")
        XCTAssertEqual(UsageFormat.duration(ms: 754_000), "13m")
        XCTAssertEqual(UsageFormat.duration(ms: 5_400_000), "1h 30m")
    }

    /// A harness dict value straight off the wire: an integer groups, a
    /// string passes through, a missing value is an em dash. `LooseValue.text`
    /// alone rendered "1284" and "—" inconsistently across the panel.
    func testHarnessValue() {
        XCTAssertEqual(UsageFormat.harnessValue(nil), "—")
        XCTAssertEqual(UsageFormat.harnessValue(.null), "—")
        XCTAssertEqual(UsageFormat.harnessValue(.number(1284)), "1,284")
        XCTAssertEqual(UsageFormat.harnessValue(.string("2026-01-04")), "2026-01-04")
    }
}
