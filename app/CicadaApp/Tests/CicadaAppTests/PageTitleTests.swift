import XCTest
@testable import CicadaApp

/// Live check 2026-09-23 (Z-B4) — the Sleep page's title was still SF 20
/// semibold after G137 R-M16 moved every page title to the display face,
/// because it spelled its own `Text(…).font(titleFont)` instead of sharing
/// `PageHeader`'s. One title view now, and both draw through it.
final class PageTitleTests: XCTestCase {

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) })
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// The Sleep redesign (owner, 2026-10-16: "remove the title Sleep Cycle") — the page opens on its eyebrow like a
    /// list page (DR-25); `PageTitle` survives on Home alone of the pages.
    func test_theSleepPageHasNoTitleOnlyItsEyebrow() throws {
        let text = try source("Views/Sleep/SleepView.swift")
        XCTAssertFalse(text.contains("PageTitle("), "no title band on the Sleep page")
        XCTAssertTrue(text.contains("EyebrowRow(eyebrow: SleepEyebrow.text("))
        XCTAssertFalse(text.contains("CicadaTheme.titleFont"), "the SF 20 semibold title G137 retired")
        XCTAssertFalse(text.contains("Sleep Cycle"))
    }

    func test_pageHeaderDrawsItsTitleThroughTheSameView() throws {
        let text = try source("Views/Common/PageHeader.swift")
        XCTAssertTrue(text.contains("PageTitle(title)"))
        XCTAssertEqual(text.components(separatedBy: "displayFont(").count - 1, 1,
                       "the title face is spelled once, inside PageTitle")
    }

    func test_theTitleIsTheDisplayFaceAtItsSize() {
        XCTAssertEqual(PageTitle.size, 28)
        XCTAssertGreaterThanOrEqual(PageTitle.size, CicadaTheme.displayMinimumSize)
    }
}
