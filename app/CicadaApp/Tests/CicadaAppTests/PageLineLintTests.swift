import XCTest
@testable import CicadaApp

/// Owner 2026-11-23: *"it should always be rendered"* — a link never shows as `[[example]]` anywhere in the app.
/// `PageLine` is the one door for page text shown as a plain line; this lint fails a view that draws such text without
/// it, the way `SoftCardTests` fails a hand-spelled card.
///
/// **How to stay inside it.** A new view that shows a page's words, a claim's, a question's or a search passage as a
/// `Text`, a tooltip or an accessibility label uses `PageLineText(raw)`, `.pageHelp(raw)`, `PageLine.plain(raw, links:)`
/// or `renderWikilinks(raw, links:)`. When a new field carries page text, add its spelling to `pageTextFields` below —
/// that is the whole cost, and it makes the next view that draws it raw fail here.
final class PageLineLintTests: XCTestCase {
    /// The doors: a line that names one is page text done right.
    private static let doors = ["PageLine", "pageHelp", "pageAccessibilityLabel", "renderWikilinks", "MarkdownBody",
                                "inlineAttributed", "links: store"]

    /// Where a string is drawn or spoken.
    private static let sinks = ["Text(", ".help(", ".accessibilityLabel(", ".accessibilityValue(", "Label(",
                                "TextButton(title:", "NeutralButton(title:", "InlineLink(title:", "FullListSheet(title:"]

    /// Page text as the app holds it: each is a field a page, a claim, a question or a search hit wrote into the bank.
    /// A spelling matches as a substring of a line that also holds a sink.
    private static let pageTextFields = [
        "item.askText", "item.questionText", "item.askReason", "row.askText",      // an inbox question and its reason
        "row.question",                                                            // Home's lead question
        "option.description", "answer.label", "chip.label",                        // an inbox option, a catch-up chip
        "row.snippet", "citation.snippet", "hit.snippet",                           // a search passage, an Ask citation
        "p.summary", "side.summary", "node.summary", "subject?.summary",           // a page's summary line
        "claim.text",                                                              // a belief
        "ClustersModel.line(", "ClustersModel.tileLine(", "ClustersModel.detail(", // a list row's one line
    ]

    /// Files another change owns, with the reason. Each is a gap to close, never a place to add to: the entity page's
    /// own text path is being reworked in its own PR (the page-text worker's `Views/Graph/Page*`), so this change leaves
    /// it alone and says so.
    private static let knownGaps = [
        "PageQuestionsStrip.swift",   // the entity page's questions strip: askText and its chips, drawn raw
    ]

    /// Lines that name a field without drawing page text (a count, a guard, a key).
    private static let exempt = [".isEmpty", ".count", "== nil", "!= nil", "key:", "id:", "Copy."]

    private func lines(under folders: [String]) throws -> [(file: String, number: Int, text: String)] {
        var out: [(String, Int, String)] = []
        for file in try ThemeTokenTests.swiftSources() where folders.contains(where: { file.path.contains("/\($0)/") }) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: "\n").enumerated() {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.hasPrefix("//") || trimmed.hasPrefix("///") { continue }
                out.append((file.lastPathComponent, index + 1, line))
            }
        }
        return out
    }

    /// A view that draws a registered page-text field without a door shows its brackets.
    func testNoViewDrawsPageTextWithoutTheDoor() throws {
        var offenders: [String] = []
        for (file, number, line) in try lines(under: ["Views", "Search", "Ask"]) {
            guard !Self.knownGaps.contains(file), Self.sinks.contains(where: line.contains),
                  let field = Self.pageTextFields.first(where: line.contains) else { continue }
            if Self.doors.contains(where: line.contains) { continue }
            if Self.exempt.contains(where: { line.contains(field + $0) || line.contains($0 + field) }) { continue }
            // `ClustersModel.line(…)` is the door's own caller: it must pass the index.
            offenders.append("\(file):\(number): \(line.trimmingCharacters(in: .whitespaces))")
        }
        XCTAssertTrue(offenders.isEmpty,
                      "page text drawn without PageLine (a link would show as [[…]]); use PageLineText / .pageHelp / "
                      + "PageLine.plain(_, links:):\n" + offenders.joined(separator: "\n"))
    }

    /// Nothing in the views builds a link's brackets for display (the Ask chip drew `[[name]]` until 2026-11-23).
    func testNoViewSpellsABracketedName() throws {
        var offenders: [String] = []
        for (file, number, line) in try lines(under: ["Views", "Search", "Ask", "MenuBar", "SaveWhy", "ConnectSuggest"]) {
            guard line.contains("Text(\"[[") || line.contains("\"[[\\(") else { continue }
            offenders.append("\(file):\(number): \(line.trimmingCharacters(in: .whitespaces))")
        }
        XCTAssertTrue(offenders.isEmpty, "a view draws a name inside [[ ]]:\n" + offenders.joined(separator: "\n"))
    }

    /// The retired palette door: a passage goes through `PageLineText(_, excerpt: true)`, never the markup-only strip
    /// that left a link's brackets in.
    func testNoViewUsesTheMarkupOnlySnippetDoor() throws {
        var offenders: [String] = []
        for (file, number, line) in try lines(under: ["Views", "Ask", "MenuBar"]) where line.contains("cleanAttributed(") {
            offenders.append("\(file):\(number)")
        }
        XCTAssertTrue(offenders.isEmpty, "ExcerptText.cleanAttributed leaves links raw; use PageLineText:\n"
                      + offenders.joined(separator: "\n"))
    }

    /// The lint must be able to fail: it sees a raw draw of a registered field.
    func testTheLintSeesARawDraw() {
        let raw = "Text(item.askText)"
        XCTAssertTrue(Self.sinks.contains(where: raw.contains))
        XCTAssertNotNil(Self.pageTextFields.first(where: raw.contains))
        XCTAssertFalse(Self.doors.contains(where: raw.contains))
        let door = "PageLineText(item.askText)"
        XCTAssertTrue(Self.doors.contains(where: door.contains))
    }
}
