import XCTest
@testable import CicadaApp

/// G117 — every empty-state message is one sentence a person can read at a
/// glance (the same ≤60-char rule G125 R8 applies to the Sleep bubble).
final class EmptyStateViewTests: XCTestCase {
    func testEveryEmptyStateMessageIsOneShortSentence() {
        let messages = [
            Copy.emptyGraphMessage, Copy.emptyInboxMessage,
            Copy.emptyFeedMessage, Copy.emptySourcesMessage,
        ]
        for m in messages {
            XCTAssertLessThanOrEqual(m.count, 60, m)
            XCTAssertFalse(m.hasSuffix("!"), m)
        }
    }

    /// G137 R-M23 — the bookworm carries the state; the cloud is weather.
    func testTheBookwormStaysTheFocalPoint() {
        XCTAssertGreaterThan(EmptyStateLayout.cloudWidth, EmptyStateLayout.wormPointSize,
                             "a cloud narrower than the worm reads as a speck, not sky")
        XCTAssertLessThanOrEqual(EmptyStateLayout.cloudWidth, 2 * EmptyStateLayout.wormPointSize,
                                 "a cloud more than twice the worm's width competes with it")
        XCTAssertLessThanOrEqual(abs(EmptyStateLayout.cloudOffset.width), EmptyStateLayout.wormPointSize / 2,
                                 "the cloud sits behind the worm, not beside it")
        XCTAssertLessThanOrEqual(EmptyStateLayout.cornerHeight, 160)
    }

    /// Text never sits directly on paint (R-M23). A source check, because
    /// "which layer is under this Text" is not something a test can render.
    func testTheWordsSitOnASurfaceCardUnderADisplayTitle() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Common/EmptyStateView.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains(".background(CicadaTheme.surface"), "the empty state's words lost their card")
        XCTAssertTrue(text.contains("displayFont(size: 26)"))
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
        XCTAssertTrue(text.contains(".foregroundStyle(CicadaTheme.accent)"), "the quiet link lost its accent text")
        XCTAssertTrue(text.contains(".primaryActionStyle()"), "the prominent link must go through primaryActionStyle()")
    }
}
