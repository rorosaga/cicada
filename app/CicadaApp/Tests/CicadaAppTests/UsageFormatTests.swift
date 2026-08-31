import XCTest
@testable import CicadaApp

final class UsageFormatTests: XCTestCase {
    func testTokens() {
        XCTAssertEqual(UsageFormat.tokens(0), "0")
        XCTAssertEqual(UsageFormat.tokens(999), "999")
        XCTAssertEqual(UsageFormat.tokens(41_200), "41.2k")
        XCTAssertEqual(UsageFormat.tokens(1_340_000), "1.34M")
    }

    func testUsd() {
        XCTAssertEqual(UsageFormat.usd(nil), "n/a")
        XCTAssertEqual(UsageFormat.usd(0), "$0.00")
        XCTAssertEqual(UsageFormat.usd(3.126), "$3.13")
        XCTAssertEqual(UsageFormat.usd(0.0031), "$0.0031")
    }

    func testCostLineSubscriptionOnly() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 0, equivUsd: 4.2, subscriptionUsd: 200),
                       "Included in plan · ≈ $4.20 at API list price")
    }

    func testCostLineUsage() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 3.12, equivUsd: 3.12, subscriptionUsd: nil), "$3.12 spent")
    }

    func testCostLineMixed() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 3.12, equivUsd: 7.32, subscriptionUsd: 200),
                       "$3.12 spent · plan work ≈ $4.20 at API list price")
    }

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
