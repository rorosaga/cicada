import XCTest
@testable import CicadaApp

/// R-DL19…R-DL22, R-DL26 — Sources in D, pure where it can be and pinned at the source where it cannot.
final class SourcesListTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    // MARK: P4 — sections share a row

    func testSectionsPackSideBySideAndABigOneTakesWholeRows() {
        typealias P = SourceGridPacking.Placement
        XCTAssertEqual(SourceGridPacking.rows(tileCounts: [3, 1, 1, 1], columns: 4),
                       [[P(section: 0, span: 3), P(section: 1, span: 1)], [P(section: 2, span: 1), P(section: 3, span: 1)]])
        XCTAssertEqual(SourceGridPacking.rows(tileCounts: [5, 2], columns: 4),
                       [[P(section: 0, span: 4)], [P(section: 1, span: 2)]])
        XCTAssertEqual(SourceGridPacking.rows(tileCounts: [1, 1, 1], columns: 2),
                       [[P(section: 0, span: 1), P(section: 1, span: 1)], [P(section: 2, span: 1)]])
        XCTAssertEqual(SourceGridPacking.rows(tileCounts: [], columns: 3), [])
    }

    func testContributorsTakeWhatTheLastRowLeavesWhenItIsTwoOrMore() {
        let rows = SourceGridPacking.rows(tileCounts: [3, 1, 1, 1], columns: 4)
        XCTAssertTrue(SourceGridPacking.contributorsSpan(rows: rows, columns: 4) == (true, 2))
        let full = SourceGridPacking.rows(tileCounts: [2, 2], columns: 4)
        XCTAssertTrue(SourceGridPacking.contributorsSpan(rows: full, columns: 4) == (false, 4))
        let one = SourceGridPacking.rows(tileCounts: [1], columns: 2)
        XCTAssertTrue(SourceGridPacking.contributorsSpan(rows: one, columns: 2) == (false, 2), "one column left is not enough")
        XCTAssertTrue(SourceGridPacking.contributorsSpan(rows: [], columns: 3) == (false, 3))
    }

    func testTheTileIsNinetySixPointsWithItsPadding() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(SourceCardMetrics.tileHeight, 96)
        XCTAssertEqual(SourceCardMetrics.markSize, 20)
    }

    // MARK: R-DL20 / R-DL21 — colour and the Safari overflow

    func testAFailureSpeaksInWordsAndHidesItsDot() {
        XCTAssertTrue(SourceLiveness.Tone.live.showsDot)
        XCTAssertTrue(SourceLiveness.Tone.dormant.showsDot)
        XCTAssertFalse(SourceLiveness.Tone.warning.showsDot)
        XCTAssertFalse(SourceLiveness.Tone.danger.showsDot)
        XCTAssertTrue(SourceLiveness.Tone.danger.isAlarm)
        XCTAssertFalse(SourceLiveness.Tone.live.isAlarm)
    }

    func testACompactLightNeverDrawsTheFix() {
        XCTAssertTrue(BrowserStatusLight.showsFixHint(state: .blocked, hasError: true, compact: false))
        XCTAssertFalse(BrowserStatusLight.showsFixHint(state: .blocked, hasError: true, compact: true),
                       "the Safari tile that grew a paragraph")
        XCTAssertFalse(BrowserStatusLight.showsFixHint(state: .blocked, hasError: false, compact: false))
        XCTAssertFalse(BrowserStatusLight.showsFixHint(state: .failed, hasError: true, compact: false))
    }

    func testTheTilePassesTheLightNoErrorAndClipsToItsShape() throws {
        let grid = try source("Views/Sources/SourceCardGrid.swift")
        XCTAssertFalse(grid.contains("error: watchError"), "R-DL21 — the fix lives in the detail column")
        XCTAssertTrue(grid.contains(".clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))"))
        XCTAssertFalse(grid.contains("CicadaTheme.danger"), "DR-7 — danger is for destructive actions")
    }

    // MARK: R-DL22 — the contributor strip

    func testTheStripOpensAColumnAndSpendsNoAccent() throws {
        let strip = try source("Views/Contributors/ContributorsStrip.swift")
        XCTAssertFalse(strip.contains(".sheet("), "a sheet hid the Reader its own 'from conversation' opens")
        XCTAssertFalse(strip.contains("CicadaTheme.accent"), "DR-5 — a share bar is data, not the accent")
    }

    // MARK: R-DL26 — the eyebrow; R-DL6 — the order ↑/↓ walks

    private func row(_ id: String, _ kind: SourceKind) -> SourceOverview {
        SourceOverview(id: id, label: id, kind: kind)
    }

    func testTheEyebrowSaysWhereYouAre() {
        let sections = SourceSections.group([row("harness:claude-code", .harness), row("chrome-bookmarks", .browser)])
        XCTAssertEqual(SourcesModel.eyebrow(sections: sections, open: nil), "Sources · 2 connected")
        XCTAssertEqual(SourcesModel.eyebrow(sections: sections, open: .source("chrome-bookmarks")),
                       "Sources · 2 of 2 · Browsers")
        XCTAssertEqual(SourcesModel.eyebrow(sections: sections, open: .contributor("gpt-5.4-mini")),
                       "Sources · Who wrote your memory")
        XCTAssertEqual(SourcesModel.eyebrow(sections: [], open: nil), "Sources")
    }

    func testTheListWalksSourcesThenContributors() {
        let sections = SourceSections.group([row("harness:claude-code", .harness), row("rss", .feed)])
        XCTAssertEqual(SourcesModel.order(sections: sections, authors: ["gpt-5.4-mini"]),
                       [.source("harness:claude-code"), .source("rss"), .contributor("gpt-5.4-mini")])
    }

    /// R-S7's pins, restated for the rewritten page (SourcesV2Tests holds the originals).
    func testTheWayInStaysInTheEyebrowRow() throws {
        let page = try source("Views/Sources/SourcesPageView.swift")
        XCTAssertTrue(page.contains("Add a source"))
        XCTAssertTrue(page.contains("NeutralButton("))
        XCTAssertEqual(page.components(separatedBy: "AddSourceSheet(").count - 1, 1)
    }
}
