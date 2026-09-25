import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-4 / DR-5 — one accent, and it is the Mac's. A second accent literal is how the app ended
/// up with two (problem P2): a view that spells indigo, or reads the system accent itself,
/// escapes every rule the theme holds.
final class AccentSourceLintTests: XCTestCase {
    private func code(_ file: URL) throws -> [(Int, String)] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            .map { ($0.offset + 1, $0.element) }
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
    }

    func testNoBlueLiteralAnywhere() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            for (n, line) in try code(file) where [".blue)", "Color.blue", ".tint(.blue"].contains(where: line.contains) {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-4: Color.blue never appears — the accent is CicadaTheme.accent")
    }

    /// Only the theme reads the system accent; everyone else reads `CicadaTheme.accent`.
    func testOnlyTheThemeReadsTheSystemAccent() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.contains("/Theme/") {
            for (n, line) in try code(file) where line.contains("accentColor") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [])
    }

    /// R-DS6 — the retired indigo lives on exactly once per mode, as a data hue.
    func testTheRetiredIndigoIsOnlyADataHue() throws {
        for hex in ["0x8C9CFF", "0x4A5BD6"] {
            var hits: [String] = []
            for file in try ThemeTokenTests.swiftSources() {
                let count = try String(contentsOf: file, encoding: .utf8).uppercased()
                    .components(separatedBy: hex.uppercased()).count - 1
                if count > 0 { hits.append("\(file.lastPathComponent)×\(count)") }
            }
            XCTAssertEqual(hits, ["CicadaTheme.swift×1"], hex)
        }
    }
}
