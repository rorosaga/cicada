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

    /// G137 R-M3, F1 R-FX12: no face is bundled any more — `displayFont` is
    /// SF — so `.custom(` anywhere would be a second face arriving unnoticed:
    /// unscaled by ⌘+/⌘−, unregistered, unlicensed. Comment lines are skipped
    /// so a doc may name the API.
    func testNoCustomFontOutsideTheTheme() throws {
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains(".custom(") else { continue }
                XCTFail("\(file.lastPathComponent):\(index + 1) builds a custom font — "
                        + "use CicadaTheme.displayFont(size:italic:) (G137 R-M3).")
            }
        }
    }

    /// Display is a role — a title — not a size (F1 R-FX12): a display call
    /// under 22 pt is a heading in the wrong token. `displayFont` clamps, and
    /// this keeps a call site from asking.
    func testDisplayFontIsNeverAskedForLessThanItsFloor() throws {
        let pattern = try NSRegularExpression(pattern: #"displayFont\(size:\s*([0-9]+(?:\.[0-9]+)?)"#)
        var seen = 0
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let ns = text as NSString
            for match in pattern.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
                let size = Double(ns.substring(with: match.range(at: 1))) ?? 0
                XCTAssertGreaterThanOrEqual(size, Double(CicadaTheme.displayMinimumSize),
                                            "\(file.lastPathComponent) asks for a \(size) pt display face")
                seen += 1
            }
        }
        XCTAssertGreaterThan(seen, 0, "no displayFont call found — the regex no longer matches and this lint is vacuous")
    }

    /// F1 R-FX12: `Font` cannot carry tracking, so every roman display title
    /// pairs `.font(CicadaTheme.displayFont(size: n))` with
    /// `.tracking(CicadaTheme.displayTracking(size: n))`. Counted per file —
    /// a new title without its tracking fails here, not in a screenshot.
    /// Italic lines keep SF's own spacing and are not counted.
    func testEveryRomanDisplayTitleCarriesItsTracking() throws {
        var seen = 0
        for file in try sourceFiles() {
            let code = try String(contentsOf: file, encoding: .utf8)
                .components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            let roman = code.filter { $0.contains("displayFont(size:") && !$0.contains("italic: true") }.count
            let tracked = code.filter { $0.contains("displayTracking(size:") }.count
            XCTAssertEqual(roman, tracked, "\(file.lastPathComponent): \(roman) roman displayFont call(s) "
                           + "but \(tracked) displayTracking — pair each title with its tracking (F1 R-FX12).")
            seen += roman
        }
        XCTAssertGreaterThan(seen, 0, "no roman displayFont call found — this lint would pass vacuously")
    }

    /// DR-15 / DR-18 — SF only. New York was the last second face; `design: .serif` anywhere
    /// would bring it back unannounced.
    func testNoSerifFaceSurvives() throws {
        for file in try sourceFiles() + [URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Theme/CicadaTheme.swift")] {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("design: .serif"), file.lastPathComponent)
        }
    }

    /// F1 R-FX12: nothing is bundled any more. A font file under Resources/
    /// would be a second face arriving unregistered, unlicensed and unscaled.
    func testNoFontFileIsBundled() throws {
        let resources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp/Resources")
        let all = FileManager.default.enumerator(at: resources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL } ?? []
        XCTAssertFalse(all.isEmpty, "found nothing under \(resources.path) — the lint would pass vacuously")
        let fonts = all.filter { ["ttf", "otf", "ttc", "woff", "woff2"].contains($0.pathExtension.lowercased()) }
        XCTAssertEqual(fonts.map(\.lastPathComponent), [])
    }
}
