import XCTest
@testable import CicadaApp

/// DR-57 (QA 2026-10-16, finding 11) — ⌘K labelled an RSS item and a calendar event "You said". The palette names the
/// true speaker: what arrived from a feed or a calendar is not the person's words.
final class FindSpeakerTests: XCTestCase {
    func test_aFeedOrCalendarPassageIsNeverYouSaid() {
        XCTAssertEqual(FindServerRows.speaker("user", origin: "rss"), "From the feed")
        XCTAssertEqual(FindServerRows.speaker("user", origin: "calendar"), "On your calendar")
        XCTAssertEqual(FindServerRows.speaker("user", origin: "calendar-local"), "On your calendar")
    }

    func test_thePersonsOwnWordsStillReadYouSaid() {
        XCTAssertEqual(FindServerRows.speaker("user", origin: "claude-code"), "You said")
        XCTAssertEqual(FindServerRows.speaker("user"), "You said")
        XCTAssertEqual(FindServerRows.speaker("assistant", origin: "rss"), "Agent replied", "only the person's side moves")
    }
}
