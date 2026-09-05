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

    // MARK: - Dark-mode resolution (Track L, R-L5)

    /// R-L5 — a monochrome mark ships a `-dark` sibling and `LogoImage` picks
    /// it under a dark theme. `CicadaTheme.surfaceElevated` is `#23252E` in
    /// dark, so a black-on-transparent ChatGPT mark is simply invisible there;
    /// the white plate `AgentTile` used to paper over this with is worse than
    /// the disease (it puts every COLOUR mark on a white chip).
    func testDarkModePrefersTheDarkSiblingWhenOneIsBundled() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }

        CicadaTheme.mode = .dark
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt"), "chatgpt-dark")
        XCTAssertEqual(LogoImage.resolvedName(for: "x"), "x-dark")
        // A colour mark has no sibling and must not be rewritten.
        XCTAssertEqual(LogoImage.resolvedName(for: "chrome"), "chrome")

        CicadaTheme.mode = .light
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt"), "chatgpt")
        XCTAssertEqual(LogoImage.resolvedName(for: "chrome"), "chrome")
    }

    /// An id nothing bundles resolves to nil in both themes — the caller's
    /// SF-Symbol fallback, never a blank square.
    func testAnUnbundledNameResolvesToNilInBothModes() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertNil(LogoImage.resolvedName(for: "not-a-real-mark"))
        }
    }

    /// The empty name is not a name. `ConnectedChannelRow.rowIcon`,
    /// `IntegrationsView.mark` and `MemberMark` all pass `logoName ?? ""`,
    /// because R6 makes them take the platform tile whenever EITHER rung
    /// exists — and Foundation resolves an empty resource name to the FIRST
    /// file in the directory, which is `rss.png` today. Without the guard, a
    /// Safari or Apple Notes row on a Mac where that app is absent drew the RSS
    /// mark. The assertion is `false`/nil, not "not rss": the defect is
    /// resolving at all, and a new alphabetically-first asset must not be able
    /// to make this test pass for the wrong reason.
    func testTheEmptyNameIsNeverAMark() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertFalse(LogoImage.exists(name: ""), "\(mode)")
            XCTAssertNil(LogoImage.resolvedName(for: ""), "\(mode)")
        }
    }

    /// A `-dark` file is never reachable on its own: asking for the sibling by
    /// name must not append a second suffix.
    func testADarkNameIsNeverDoubleSuffixed() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        CicadaTheme.mode = .dark
        XCTAssertEqual(LogoImage.resolvedName(for: "chatgpt-dark"), "chatgpt-dark")
    }
}
