import XCTest
@testable import CicadaApp

/// G136 A6 / plan R-SU9 — ⌘K and ⌘F are menu commands in one file. A hidden
/// zero-size button with either shortcut is how ⌘F used to fire on the
/// graph's invisible field from another tab (the graph stays mounted), and a
/// behaviour test cannot see a literal arrive in a diff.
final class HiddenShortcutLintTests: XCTestCase {
    static let home = "Support/FindCommands.swift"
    static let needles = [#".keyboardShortcut("k""#, #".keyboardShortcut("f""#]

    func testFindShortcutsLiveOnlyInTheMenuCommands() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.hasSuffix(Self.home) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "⌘K/⌘F belong to FindCommands (G136 A6)")
    }

    func testTheHomeFileDeclaresBoth() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(Self.home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        for needle in Self.needles { XCTAssertTrue(text.contains(needle), "\(needle) — the lint would pass vacuously") }
    }
}
