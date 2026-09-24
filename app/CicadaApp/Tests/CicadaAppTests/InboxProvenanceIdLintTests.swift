import XCTest
@testable import CicadaApp

/// DR-54 (scoped to the Inbox, R-DI23) — a source is named the way a person would. An episode id, a
/// harness slug or an origin id reaches the Inbox's screen only through `.help`, an accessibility
/// label or a copy action — never interpolated into a `Text`.
final class InboxProvenanceIdLintTests: XCTestCase {
    static let needles = ["\\(cause.harness", "\\(cause.origin", "\\(cause.episodeId", "\\(item.cause", "ep_"]

    func testTheInboxNeverPrintsAnIdOrASlug() throws {
        let files = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/Inbox/") }
        XCTAssertGreaterThanOrEqual(files.count, 6, "the scope moved — this lint would pass vacuously")
        var offenders: [String] = []
        for file in files {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains("Text(") {
                if Self.needles.contains(where: line.contains) { offenders.append("\(file.lastPathComponent):\(i + 1)") }
            }
        }
        XCTAssertEqual(offenders, [], "DR-54 — name the source through InboxSourceLine")
    }
}
