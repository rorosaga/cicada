import XCTest
@testable import CicadaApp

/// Owner 2026-11-05 ("Sources should always have their logos"): T3 Code and Grok had their marks bundled and drew a tray,
/// because the origin map had no row for them. Every harness the backend can name and every catalog tile resolves to a
/// real mark here, or is on the one named list below.
final class SourceMarkCoverageTests: XCTestCase {
    /// Not brands: generic buckets and tiles that hold what the person brings. They keep a neutral glyph.
    /// `hex` is the one brand here: its row is offered only when the app is on this Mac, so its own icon draws, and no
    /// faithful file has been sourced for the bundle yet.
    static let noBrand: Set<String> = [
        "remote-app", "agent-api", "unknown",
        SourceCatalog.chatExportsOrigin, SourceCatalog.filesOrigin, SourceCatalog.meetingFoldersId, SourceCatalog.tracesId,
        "folder", "book-scan", "calendar",
        SourceCatalog.hexId,
    ]

    /// A bundled file, or Apple's own app (its marks are never committed, so the installed icon is its only mark).
    private func hasRealMark(_ origin: String) -> Bool {
        if let name = OriginIconography.logoName(for: origin), LogoImage.exists(name: name) { return true }
        return OriginIconography.appBundleId(for: origin)?.hasPrefix("com.apple.") == true
    }

    private func harnessLabels() throws -> [String] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let text = try String(contentsOf: root.appendingPathComponent("api/services/source_overview.py"), encoding: .utf8)
        let start = try XCTUnwrap(text.range(of: "HARNESS_LABELS = {\n"), "HARNESS_LABELS moved")
        let end = try XCTUnwrap(text.range(of: "\n}", range: start.upperBound..<text.endIndex))
        let keys = text[start.upperBound..<end.lowerBound].split(separator: "\n").compactMap { line -> String? in
            // `    "claude-code": "Claude Code",` — a `# comment` line opens with no quote.
            guard line.drop(while: \.isWhitespace).hasPrefix("\"") else { return nil }
            return line.split(separator: "\"", omittingEmptySubsequences: false).dropFirst().first.map(String.init)
        }
        XCTAssertTrue(keys.contains("t3code") && keys.contains("claude-code"), "the parse found \(keys)")
        return keys
    }

    private func catalogOrigins() -> [String] {
        SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported), wisprPresent: true, hexPresent: true, overview: [])
            .map(\.origin)
    }

    func testEveryHarnessAndCatalogSourceHasARealMarkOrIsNamedAsNoBrand() throws {
        let origins = Set(try harnessLabels() + catalogOrigins())
        for origin in origins.sorted() where !Self.noBrand.contains(origin) {
            XCTAssertTrue(hasRealMark(origin), "\(origin) draws no real mark: map it to a bundled file, or say why not in `noBrand`")
        }
    }

    /// The list stays short and true: a name that gained a mark, or that no source uses any more, leaves it.
    func testTheNamedListHoldsOnlyLiveSourcesWithNoBundledMark() throws {
        let origins = Set(try harnessLabels() + catalogOrigins())
        for name in Self.noBrand.sorted() {
            XCTAssertTrue(origins.contains(name), "\(name) is no longer a source")
            XCTAssertNil(OriginIconography.logoName(for: name), "\(name) has a mark now")
        }
    }

    func testTheBrandsThatDrewATrayNowHaveTheirMarks() {
        for (origin, file) in [("t3code", "t3"), ("grok", "grok"), ("perplexity", "perplexity"), ("comet-bookmark", "comet")] {
            let name = OriginIconography.logoName(for: origin)
            XCTAssertEqual(name.map { BrandMark.composition(for: $0).file }, file, origin)
        }
    }
}
