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
}
