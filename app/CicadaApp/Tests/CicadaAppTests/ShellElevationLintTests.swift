import XCTest
@testable import CicadaApp

/// DR-9 / DR-10 / DR-11 / DR-12, scoped to the files this track creates (R-DS28): no shadow, no
/// border stroke, no divider, no bare rounded rectangle. The app-wide versions are page-track
/// sweeps; new code starts clean.
final class ShellElevationLintTests: XCTestCase {
    static let scoped = ["/Views/Shell/", "/Views/Find/FindPalette.swift", "/Views/Settings/SettingsPanel.swift"]
    static let needles = [".shadow(", ".stroke(CicadaTheme.border", "Divider()", "RoundedRectangle(cornerRadius:"]

    func testTheShellDrawsDepthWithRings() throws {
        var offenders: [String] = []
        let files = try ThemeTokenTests.swiftSources().filter { f in Self.scoped.contains { f.path.contains($0) } }
        XCTAssertFalse(files.isEmpty)
        for file in files {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                for needle in Self.needles where line.contains(needle) { offenders.append("\(file.lastPathComponent):\(i + 1) \(needle)") }
            }
        }
        XCTAssertEqual(offenders, [])
    }
}
