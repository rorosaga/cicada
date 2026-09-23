import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-25 / DR-45 — the list page's header: an eyebrow and text tabs with counts.
final class TextTabsTests: XCTestCase {
    /// Single-select; tapping the active tab returns to All (nil).
    func testTappingTheActiveTabReturnsToAll() {
        XCTAssertEqual(TextTabSelection.next(tapping: "decay", current: nil), "decay")
        XCTAssertNil(TextTabSelection.next(tapping: "decay", current: "decay"))
        XCTAssertEqual(TextTabSelection.next(tapping: "conflict", current: "decay"), "conflict")
        XCTAssertNil(TextTabSelection.next(tapping: nil, current: "decay"), "All")
        XCTAssertNil(TextTabSelection.next(tapping: nil as String?, current: nil))
    }

    func testTheSpokenLabelCarriesTheCount() {
        XCTAssertEqual(TextTabSelection.accessibilityLabel(label: "Decay", count: 1), "Decay, 1")
        XCTAssertEqual(TextTabSelection.accessibilityLabel(label: "All", count: nil), "All")
    }

    /// "Inbox · 6 pending" — parts joined by a middle dot, empty parts dropped.
    func testTheEyebrowJoinsItsParts() {
        XCTAssertEqual(Eyebrow.text("Inbox", "6 pending"), "Inbox · 6 pending")
        XCTAssertEqual(Eyebrow.text("Inbox", "1 of 6", "Conflict"), "Inbox · 1 of 6 · Conflict")
        XCTAssertEqual(Eyebrow.text("Clusters", ""), "Clusters")
    }

    func testTheRowSitsTwentyBelowTheTitlebarAtLeast28Tall() {
        XCTAssertEqual(EyebrowRow<EmptyView>.topPadding, 20)
        XCTAssertEqual(EyebrowRow<EmptyView>.minHeight, 28)
        XCTAssertEqual(TextTabs<String>.height, 26)
        XCTAssertEqual(TextTabs<String>.horizontalPadding, 9)
    }
}
