import XCTest
@testable import CicadaApp

/// G124 (2026-09-03 ruling): `UsageFormat.tokens`, `.usd` and `.costLine`
/// are gone with the prices and token counts they formatted — only the
/// count/percent/duration/harness formatters remain.
final class UsageFormatTests: XCTestCase {
    // MARK: G68 §2.5 — harness numbers go through UsageFormat too

    /// R-S17 moved `count`'s default off the `en_US_POSIX` pin and onto
    /// `Locale.autoupdatingCurrent`, so these assertions name the locale they
    /// mean. Without that they would be green on an `en` host and red on a
    /// `de` one — asserting the tester's Mac, not the formatter.
    func testCount() {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(UsageFormat.count(0, locale: en), "0")
        XCTAssertEqual(UsageFormat.count(999, locale: en), "999")
        XCTAssertEqual(UsageFormat.count(1_284, locale: en), "1,284")
        XCTAssertEqual(UsageFormat.count(1_284_000, locale: en), "1,284,000")
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
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(UsageFormat.harnessValue(nil), "—")
        XCTAssertEqual(UsageFormat.harnessValue(.null), "—")
        // Compared against `count`'s own output rather than a literal: the
        // point of this case is that `harnessValue` ROUTES through `count`,
        // and since R-S17 that answer is the reader's locale, not "en_US".
        XCTAssertEqual(UsageFormat.harnessValue(.number(1284)), UsageFormat.count(1284))
        XCTAssertEqual(UsageFormat.harnessValue(.string("2026-01-04")), "2026-01-04")
        // R-S17's "one formatter, one locale, no second door": `harnessValue`
        // takes and FORWARDS the same defaulted `locale:`, so a harness tile
        // can never be the one number on screen grouped a different way.
        XCTAssertEqual(UsageFormat.harnessValue(.number(1284), locale: Locale(identifier: "de_DE")),
                       "1.284")
        XCTAssertEqual(UsageFormat.harnessValue(.number(1284), locale: en), "1,284")
    }
}
