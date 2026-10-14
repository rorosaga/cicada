import XCTest
@testable import CicadaApp

/// Review re-check of the sources view: the card passes `overview == nil` to the closed section's summary until the section or
/// the beliefs list opens. On a page with sources and no conversations yet it then says "nothing recorded yet".
final class PageSourcesClosedSummaryTests: XCTestCase {
    func testClosedSummaryNeverClaimsNothingBeforeTheOverviewIsRead() {
        // The card's call while closed: no overview yet, /provenance says 0 conversations.
        let closed = PageSourcesWords.summary(nil, conversations: 0)
        XCTAssertNil(closed, "the sources were never read, so the section cannot say nothing is recorded")
    }

    func testClosedSummaryDoesNotChangeAfterOpeningAndClosing() {
        let site = PageSource(source: PageSourcesTests.source("https://alpha-co.example/"), site: "alpha-co.example")
        let read = PageSourcesOverview(entityId: "alpha-co", sources: [site],
                                       conversations: PageConversations(total: 3))
        XCTAssertEqual(PageSourcesWords.summary(nil, conversations: 3), PageSourcesWords.summary(read),
                       "the closed section's count before and after a first open")
    }
}
