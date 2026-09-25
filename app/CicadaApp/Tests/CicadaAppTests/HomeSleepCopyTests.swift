import XCTest
@testable import CicadaApp

/// DR-59 over DS-3b's words: short labels, plain, sentence case, no "!", no bare "%", and no price,
/// token or "$" (the 2026-09-03 ruling). A new string joins `Copy.homeSleepLabels` or this lint
/// does not see it.
final class HomeSleepCopyTests: XCTestCase {
    func testDSThreeBCopyIsShortPlainAndPriceless() {
        XCTAssertGreaterThan(Copy.homeSleepLabels.count, 8, "a lint over nothing passes vacuously")
        for label in Copy.homeSleepLabels {
            XCTAssertLessThanOrEqual(label.count, 60, label)
            XCTAssertFalse(label.contains("!"), label)
            XCTAssertFalse(label.contains("$"), label)
            XCTAssertFalse(label.lowercased().contains("token"), label)
            XCTAssertFalse(label.contains("**"), "\(label) — no glob jargon (R-HS17)")
            XCTAssertEqual(label.first.map { String($0) }, label.first.map { String($0).uppercased() },
                           "\(label) — sentence case starts with a capital")
        }
    }
}
