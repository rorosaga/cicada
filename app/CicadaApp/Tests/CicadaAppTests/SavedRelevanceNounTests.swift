import XCTest
@testable import CicadaApp

/// DR-59 — no bare percentage. Sleep → Saved's rows printed "90%" with nothing after it (QA 2026-10-16).
final class SavedRelevanceNounTests: XCTestCase {
    func testTheRowsRelevanceCarriesItsNoun() {
        XCTAssertEqual(Copy.Lists.relevanceShort(UsageFormat.percent(90)), "90% relevant")
    }

    func testTheRowDoesNotPrintABarePercent() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Feed/FeedRows.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("Text(UsageFormat.percent(item.relevance * 100))"))
        XCTAssertTrue(text.contains("Copy.Lists.relevanceShort("))
    }
}
