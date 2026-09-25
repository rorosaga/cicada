import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M21 — "art never on the graph, a list, a grid, a form
/// or a number" as a build failure, not a doc comment. A painted component
/// may be named only inside `Views/Meadow/` and by the files listed here;
/// adding one is a design decision a reviewer sees in the diff (the same
/// deliberate-act shape as `SleepNumbersLintTests`' noun list).
final class MeadowPlacementLintTests: XCTestCase {
    static let allowed: [String] = [
        "Views/Common/EmptyStateView.swift",   // G137 M1: grass corners + one cloud behind the worm
    ]
    static let needles = ["MeadowBackdrop(", "DriftingCloud(", "GrassCorners(", "GrassEdge(",
                          "MeadowSky(", "ArtImage(", "MeadowArt.image(",
                          "PaintedScene(", "PaintedSceneFrame("]

    func testPaintedArtIsDrawnOnlyWhereARulingAllowsIt() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            let path = file.path
            guard !path.contains("/Views/Meadow/"), !Self.allowed.contains(where: { path.hasSuffix($0) }) else { continue }
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "painted art outside its allowlist — never on data surfaces (G137 R-M6)")
    }

    func testTheAllowlistNamesRealFiles() throws {
        let paths = try ThemeTokenTests.swiftSources().map(\.path)
        for allowed in Self.allowed {
            XCTAssertTrue(paths.contains { $0.hasSuffix(allowed) }, "\(allowed) no longer exists — drop it")
        }
    }
}
