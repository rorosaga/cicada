import XCTest
@testable import CicadaApp

/// DR-20 / DR-47 — one section label: sentence case, `labelFont`, `textTertiary`. The ~27 hand-
/// spelled caps labels in 10 pt semibold mono with 1.2 tracking were the loudest thing on every
/// page they sat on (P1); a source lint because "a literal exists in the diff" is not
/// something a rendered view can tell you (FontLiteralLintTests' reasoning).
final class SectionLabelLintTests: XCTestCase {
    private func lines(_ file: URL) throws -> [(Int, String)] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            .map { ($0.offset + 1, $0.element) }
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
    }

    /// Tracking is the display face's own (paired, counted by FontLiteralLintTests) — nothing else.
    func testTrackingIsOnlyTheDisplayFaces() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.contains("/Theme/") {
            for (n, line) in try lines(file) where line.contains(".tracking(") && !line.contains(".tracking(CicadaTheme.displayTracking(") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-20: tracked labels are retired — use SectionLabel")
    }

    func testSectionLabelsAreSentenceCaseAndNeverUppercased() throws {
        let literal = try NSRegularExpression(pattern: #"SectionLabel\("([^"]*)"\)"#)
        var seen = 0
        for file in try ThemeTokenTests.swiftSources() {
            for (n, line) in try lines(file) where line.contains("SectionLabel(") {
                XCTAssertFalse(line.contains(".uppercased()"), "\(file.lastPathComponent):\(n) uppercases a label")
                let ns = line as NSString
                for m in literal.matches(in: line, range: NSRange(location: 0, length: ns.length)) {
                    let text = ns.substring(with: m.range(at: 1))
                    XCTAssertNotNil(text.rangeOfCharacter(from: .lowercaseLetters), "\(file.lastPathComponent):\(n) \"\(text)\" is caps")
                    seen += 1
                }
            }
        }
        XCTAssertGreaterThan(seen, 10, "the regex no longer matches — this lint would pass vacuously")
    }

    /// One door: `labelFont` is read by `SectionLabel` and nothing else outside the theme.
    func testLabelFontHasOneReader() throws {
        let readers = try ThemeTokenTests.swiftSources()
            .filter { !$0.path.contains("/Theme/") }
            .filter { try String(contentsOf: $0, encoding: .utf8).contains("labelFont") }
            .map(\.lastPathComponent)
        XCTAssertEqual(readers, ["SectionLabel.swift"])
    }
}
