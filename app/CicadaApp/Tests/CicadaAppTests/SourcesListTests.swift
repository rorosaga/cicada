import XCTest
@testable import CicadaApp

/// R-DL19…R-DL22, R-DL26 — Sources in D, pure where it can be and pinned at the source where it cannot.
final class SourcesListTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
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

    func testARowPassesNoErrorAndSpendsNoDanger() throws {
        let rows = try source("Views/Sources/SourcesColumns.swift")
        XCTAssertFalse(rows.contains("error: watchError"), "R-DL21 — the fix lives in the detail column")
        XCTAssertFalse(rows.contains("CicadaTheme.danger"), "DR-7 — danger is for destructive actions")
    }

    // MARK: R-DL22 — the contributor strip

    func testTheStripOpensAColumnAndSpendsNoAccent() throws {
        let strip = try source("Views/Contributors/ContributorsStrip.swift")
        XCTAssertFalse(strip.contains(".sheet("), "a sheet hid the Reader its own 'from conversation' opens")
        XCTAssertFalse(strip.contains("CicadaTheme.accent"), "DR-5 — a share bar is data, not the accent")
    }

    // MARK: R-DL26 — the eyebrow; R-DL6 — the order ↑/↓ walks

    private func row(_ id: String, _ kind: SourceKind, _ intent: SourceIntent = .captured,
                     last: String? = nil) -> SourceOverview {
        SourceOverview(id: id, label: id, kind: kind, lastActivityAt: last, intent: intent)
    }

    func testTheEyebrowSaysWhereYouAre() {
        let groups = SourceIntentGroups.group([row("harness:claude-code", .harness),
                                               row("chrome-bookmarks", .browser, .saved)])
        XCTAssertEqual(SourcesModel.eyebrow(groups: groups, open: nil), "Sources · 2 connected")
        XCTAssertEqual(SourcesModel.eyebrow(groups: groups, open: .source("chrome-bookmarks")),
                       "Sources · 1 of 2 · Saved by you")
        XCTAssertEqual(SourcesModel.eyebrow(groups: groups, open: .source("harness:claude-code")),
                       "Sources · 2 of 2 · Captured for you")
        XCTAssertEqual(SourcesModel.eyebrow(groups: groups, open: .contributor("gpt-5.4-mini")),
                       "Sources · Who wrote your memory")
        XCTAssertEqual(SourcesModel.eyebrow(groups: [], open: nil), "Sources")
    }

    func testTheListWalksSavedThenCaptured() {
        let groups = SourceIntentGroups.group([row("harness:claude-code", .harness), row("rss", .feed),
                                               row("x", .social, .saved)])
        XCTAssertEqual(SourcesModel.order(groups: groups),
                       [.source("x"), .source("harness:claude-code"), .source("rss")],
                       "who wrote the memory lives under Statistics now, so authors are not walked")
    }

    /// R-S7's pins, restated for the rewritten page (SourcesV2Tests holds the originals).
    func testTheWayInStaysInTheEyebrowRow() throws {
        let page = try source("Views/Sources/SourcesPageView.swift")
        XCTAssertTrue(page.contains("Add a source"))
        XCTAssertTrue(page.contains("NeutralButton("))
        XCTAssertEqual(page.components(separatedBy: "AddSourceSheet(").count - 1, 1)
    }
}
