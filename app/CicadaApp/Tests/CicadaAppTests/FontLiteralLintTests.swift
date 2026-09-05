import XCTest
@testable import CicadaApp

/// G130 R3: every literal `.system(size:)` / `Font.system(size:)` in the app
/// went through the mechanical migration onto `CicadaTheme.font(size:...)` so
/// ⌘+/⌘−/⌘0 (G130 slice 1a, PR #54) reach it. A source lint, not a behavior
/// test, because the defect is "a literal exists in the diff" — nothing a
/// rendered view's output would tell you apart from a scale bug.
final class FontLiteralLintTests: XCTestCase {
    /// `Theme/CicadaTheme.swift` is the one file allowed to contain a literal
    /// — it's where `CicadaTheme.font(size:...)` itself calls `.system(size:)`.
    private static let excludedFile = "Theme/CicadaTheme.swift"

    private func sourceFiles() throws -> [URL] {
        // …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp")
        let all = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" }
            .filter { !$0.path.hasSuffix(Self.excludedFile) } ?? []
        XCTAssertFalse(all.isEmpty, "found no sources under \(sources.path) — the lint would pass vacuously")
        return all
    }

    func testNoLiteralSystemFontSizeSurvives() throws {
        let needles = [".system(size:", "Font.system(size:"]
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                for needle in needles where line.contains(needle) {
                    XCTFail(
                        "\(file.lastPathComponent):\(index + 1) still has a literal \(needle) — "
                        + "route it through CicadaTheme.font(size:weight:design:) instead (G130 R3)."
                    )
                }
            }
        }
    }
}
