import XCTest
@testable import CicadaApp

/// R-DL17 — the Feed's header bug is removed by construction; this pins the construction. A hosted-window test would
/// see the titlebar, but a headless `swift test` process must never create NSApp (`AppRouter.activateMainWindow`).
final class FeedLayoutPinTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheEyebrowIsTheOnlyFixedBand() throws {
        let page = try source("Views/Feed/FeedPage.swift")
        XCTAssertTrue(page.contains("ProgressiveColumns("))
        XCTAssertFalse(page.contains("PageHeader("), "DR-25 — no page-title band")
        XCTAssertFalse(page.contains("ZStack"), "no layer that centres the page or floats a control over it")
        // No paren: a trailing-closure call (`ConnectedChannelsStrip { … }`) must not slip past the pin.
        XCTAssertFalse(page.contains("ConnectedChannelsStrip"), "the strips scroll with the list, not above it")
        let rows = try source("Views/Feed/FeedRows.swift")
        let scroll = try XCTUnwrap(rows.range(of: "ScrollView {"))
        let strip = try XCTUnwrap(rows.range(of: "ConnectedChannelsStrip("))
        XCTAssertLessThan(scroll.lowerBound, strip.lowerBound, "inside the list column's ScrollView")
    }

    func testThePlusIsInTheEyebrowWithItsShortcut() throws {
        let page = try source("Views/Feed/FeedPage.swift")
        XCTAssertTrue(page.contains(#"IconButton(systemName: "plus""#))
        XCTAssertTrue(page.contains(#"KeyboardShortcut("n", modifiers: .command)"#))
        XCTAssertFalse(page.contains(".opacity(0)"), "the hidden zero-size button is gone")
        XCTAssertEqual(page.components(separatedBy: "AddSourceSheet(").count - 1, 1)
    }
}
