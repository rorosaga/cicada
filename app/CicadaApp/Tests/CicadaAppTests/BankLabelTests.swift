import XCTest
@testable import CicadaApp

/// DR-21 — a count carries its noun in the right number. The bank menu read "default  (1 entities · 0 episodes)" on a
/// fresh install (QA 2026-10-16).
final class BankLabelTests: XCTestCase {
    func testOneOfEachIsSingular() {
        XCTAssertEqual(BankSwitcher.label(name: "default", entities: 1, episodes: 1), "default (1 entity · 1 conversation)")
    }

    func testOtherCountsArePlural() {
        XCTAssertEqual(BankSwitcher.label(name: "demo", entities: 74, episodes: 0), "demo (74 entities · 0 conversations)")
    }

    func testAnEmptyBankIsItsName() {
        XCTAssertEqual(BankSwitcher.label(name: "fresh", entities: 0, episodes: 0), "fresh")
    }
}
