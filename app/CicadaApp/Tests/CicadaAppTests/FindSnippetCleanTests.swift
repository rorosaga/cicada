import XCTest
@testable import CicadaApp

/// DR-56 (QA 2026-10-16) — the ⌘K palette's conversation snippets are clean words: no role label, no heading marker,
/// no emphasis markers, and the server's bold ranges still land on the matched word.
final class FindSnippetCleanTests: XCTestCase {
    private func parts(_ s: AttributedString) -> (text: String, bold: [String]) {
        let text = String(s.characters)
        let bold = s.runs.filter { $0.inlinePresentationIntent == .stronglyEmphasized }
            .map { String(s[$0.range].characters) }
        return (text, bold)
    }

    func testARoleLabelGoes() {
        let raw = "user: Leo Example leads motion planning now"
        let out = parts(ExcerptText.cleanAttributed(raw, bold: [[6, 9]]))
        XCTAssertEqual(out.text, "Leo Example leads motion planning now")
        XCTAssertEqual(out.bold, ["Leo"])
    }

    func testAHeadingMarkerGoes() {
        let out = parts(ExcerptText.cleanAttributed("# Lunch with Leo Example", bold: [[13, 16]]))
        XCTAssertEqual(out.text, "Lunch with Leo Example")
        XCTAssertEqual(out.bold, ["Leo"])
    }

    func testEmphasisMarkersGo() {
        let out = parts(ExcerptText.cleanAttributed("**Attendees:** Leo Example, Maria Example", bold: [[15, 18]]))
        XCTAssertEqual(out.text, "Attendees: Leo Example, Maria Example")
        XCTAssertEqual(out.bold, ["Leo"])
    }

    func testAnOutOfRangeOffsetIsIgnored() {
        let out = parts(ExcerptText.cleanAttributed("plain words", bold: [[3, 99], [-1, 2], [5, 5]]))
        XCTAssertEqual(out.text, "plain words")
        XCTAssertEqual(out.bold, [])
    }

    func testThePaletteRowUsesTheCleanSnippet() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Find/FindRowView.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("ExcerptText.cleanAttributed(snippet"))
        XCTAssertFalse(text.contains("ExcerptText.attributed(snippet"))
    }

    /// VoiceOver reads the clean snippet too.
    func testTheRowsAccessibilityLabelIsClean() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Search/FindMerge.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("row.snippet.map { ExcerptText.stripMarkup($0, keepLines: false).text }"))
    }
}
