import XCTest
@testable import CicadaApp

/// G117 — every empty-state message is one sentence a person can read at a
/// glance (the same ≤60-char rule G125 R8 applies to the Sleep bubble).
final class EmptyStateViewTests: XCTestCase {
    func testEveryEmptyStateMessageIsOneShortSentence() {
        let messages = [
            Copy.emptyGraphMessage, Copy.emptyInboxMessage,
            Copy.SleepTabs.savedEmpty, Copy.emptySourcesMessage,
        ]
        for m in messages {
            XCTAssertLessThanOrEqual(m.count, 60, m)
            XCTAssertFalse(m.hasSuffix("!"), m)
        }
    }

    /// Owner 2026-10-16 — painted art is retired everywhere, the Inbox's "all caught up" included: an empty state is
    /// plain, well-set text (DR-50) — a 22 pt display title, the line, at most one action — with no grass, no cloud,
    /// no worm and no card around it.
    func testAnEmptyStateIsPlainWellSetText() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Common/EmptyStateView.swift")
        })
        let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }.joined(separator: "\n")
        XCTAssertEqual(EmptyStateLayout.titleSize, 22, "DR-50's title")
        XCTAssertTrue(code.contains("displayFont(size: EmptyStateLayout.titleSize)"))
        for paint in ["GrassCorners", "DriftingCloud", "BookwormView", "MeadowArt", "CicadaTheme.surface",
                      ".stroke(CicadaTheme.border"] {
            XCTAssertFalse(code.contains(paint), "\(paint) is back in the empty state")
        }
    }

    /// The Sleep page's schedule link must render exactly as before: quiet by
    /// default, and the quiet branch keeps the accent-text recipe it always
    /// had. The prominent branch reaches glass only through the one style.
    func testTheSettingsLinkIsQuietUnlessAskedToBeProminent() throws {
        XCTAssertFalse(SettingsSectionLink(section: .integrations, label: "Open").prominent)
        XCTAssertTrue(SettingsSectionLink(section: .integrations, label: "Open", prominent: true).prominent)
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Common/SettingsSectionLink.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains(".buttonStyle(.cicadaPlain)"), "the quiet link lost its plain style")
        XCTAssertTrue(text.contains(".foregroundStyle(CicadaTheme.accentText)"), "the quiet link lost its link ink (DR-5)")
        XCTAssertTrue(text.contains(".primaryActionStyle()"), "the prominent link must go through primaryActionStyle()")
    }

    /// DR-38 (QA 2026-10-16) — an empty state's message never repeats its title, and a pointer points where the thing
    /// really is.
    func testEmptyStateWordsSayEachThingOnce() {
        XCTAssertFalse(Copy.emptyGraphMessage.hasPrefix("Nothing here yet"))
        XCTAssertFalse(Copy.Skills.emptyInstalledMessage.contains("below"), "nothing is below it on Installed")
        XCTAssertTrue(Copy.Skills.emptyInstalledMessage.contains(Copy.Skills.discover))
        XCTAssertFalse(Copy.banksDetail.contains("Graph page"), "DR-24: banks switch in the search bar's menu")
    }
}
