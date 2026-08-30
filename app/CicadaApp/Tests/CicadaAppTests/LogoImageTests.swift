import XCTest
@testable import CicadaApp

/// The monogram fallback (G59). Pure string logic, so it is the one part of
/// the logo path worth unit-testing — the rest is disk and network.
final class LogoImageTests: XCTestCase {

    func testTwoWordNameGivesTwoInitials() {
        XCTAssertEqual(LogoImage.monogram(for: "Rodrigo Sagastegui"), "RS")
        XCTAssertEqual(LogoImage.monogram(for: "IE University"), "IU")
    }

    func testSingleWordNameGivesOneInitial() {
        XCTAssertEqual(LogoImage.monogram(for: "MongoDB"), "M")
        XCTAssertEqual(LogoImage.monogram(for: "cicada"), "C")
    }

    func testThreeOrMoreWordsUseTheFirstTwo() {
        XCTAssertEqual(LogoImage.monogram(for: "Acme Holdings International"), "AH")
    }

    func testLeadingNonLettersAreSkipped() {
        XCTAssertEqual(LogoImage.monogram(for: "  ~/Documents roros_lab"), "DR")
        XCTAssertEqual(LogoImage.monogram(for: "3M Company"), "3C")
    }

    func testEmptyOrSymbolOnlyNameFallsBackToAQuestionMark() {
        XCTAssertEqual(LogoImage.monogram(for: ""), "?")
        XCTAssertEqual(LogoImage.monogram(for: "   "), "?")
        XCTAssertEqual(LogoImage.monogram(for: "—"), "?")
    }

    func testMonogramIsAlwaysUppercaseAndAtMostTwoCharacters() {
        for name in ["a b c d", "über alles", "x", "Zeta"] {
            let m = LogoImage.monogram(for: name)
            XCTAssertLessThanOrEqual(m.count, 2, name)
            XCTAssertEqual(m, m.uppercased(), name)
        }
    }
}
