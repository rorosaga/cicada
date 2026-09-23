import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M9 — graph.js draws on a TRANSPARENT page (`index.html`) over the
/// SwiftUI `background`, so the only neutrals it owns are the ones it paints
/// itself: label ink, the plate behind a label, the halo, the contextless
/// edge, the node stroke. Each is a hand-copied twin of a theme token and
/// says so with a `// = Dark.x` / `// = Light.x` comment (Track P). The
/// Meadow retune is the first time every neutral moved at once, and a twin
/// that silently kept the old violet ink is exactly the drift a comment
/// cannot prevent — so this reads the comments as a contract.
final class GraphPaletteTwinTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private func graphJS() throws -> String {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp/Resources/graph/graph.js")
        return try String(contentsOf: url, encoding: .utf8)
    }

    /// `#RRGGBB` or `rgb(a)(r, g, b[, a])` → 0–255 channels.
    private func channels(css: String) -> [Int]? {
        if css.hasPrefix("#"), css.count == 7, let v = Int(css.dropFirst(), radix: 16) {
            return [(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF]
        }
        guard css.hasPrefix("rgb") else { return nil }
        let inner = css.drop(while: { $0 != "(" }).dropFirst().prefix(while: { $0 != ")" })
        let ints = inner.split(separator: ",").prefix(3)
            .compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
        return ints.count == 3 ? ints : nil
    }

    private func channels(_ color: Color) -> [Int] {
        let ns = NSColor(color).usingColorSpace(.sRGB)!
        return [ns.redComponent, ns.greenComponent, ns.blueComponent].map { Int(($0 * 255).rounded()) }
    }

    private let tokens: [String: () -> Color] = [
        "background": { CicadaTheme.background }, "surface": { CicadaTheme.surface },
        "textPrimary": { CicadaTheme.textPrimary }, "textSecondary": { CicadaTheme.textSecondary },
        "border": { CicadaTheme.border }, "borderLight": { CicadaTheme.borderLight },
    ]

    func testEveryDeclaredPaletteTwinMatchesItsThemeToken() throws {
        let twin = try NSRegularExpression(
            pattern: #"^\s*\w+:\s*"([^"]+)",\s*// = (?:CicadaTheme\.)?(Dark|Light)\.(\w+)"#)
        var checked = 0
        for line in try graphJS().components(separatedBy: .newlines) {
            let ns = line as NSString
            guard let m = twin.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else { continue }
            let css = ns.substring(with: m.range(at: 1))
            let mode: AppColorScheme = ns.substring(with: m.range(at: 2)) == "Dark" ? .dark : .light
            let name = ns.substring(with: m.range(at: 3))
            let read = try XCTUnwrap(tokens[name], "graph.js declares a twin of `\(name)`, which this test does not know")
            CicadaTheme.mode = mode
            XCTAssertEqual(channels(css: css), channels(read()),
                           "graph.js `\(line.trimmingCharacters(in: .whitespaces))` drifted from \(mode.rawValue).\(name)")
            checked += 1
        }
        XCTAssertGreaterThanOrEqual(checked, 11, "found \(checked) twins — the comment convention moved and this would pass vacuously")
    }

    /// `typeColors` "MUST stay byte-identical to CicadaTheme.entityColor(for:)"
    /// — untested until now, and data hues are the one thing the Meadow retune
    /// promises not to move (R-M1).
    func testGraphTypeColorsAreTheDarkEntityHues() throws {
        let js = try graphJS()
        let start = try XCTUnwrap(js.range(of: "const typeColors = {"))
        let end = try XCTUnwrap(js.range(of: "};", range: start.upperBound..<js.endIndex))
        let entry = try NSRegularExpression(pattern: #"^\s*(\w+):\s*"(#[0-9A-Fa-f]{6})""#)
        CicadaTheme.mode = .dark
        var checked = 0
        for line in js[start.upperBound..<end.lowerBound].components(separatedBy: .newlines) {
            let ns = line as NSString
            guard let m = entry.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)),
                  let type = EntityType(rawValue: ns.substring(with: m.range(at: 1))) else { continue }
            XCTAssertEqual(channels(css: ns.substring(with: m.range(at: 2))), channels(CicadaTheme.entityColor(for: type)),
                           "graph.js typeColors.\(type.rawValue) drifted from CicadaTheme.entityColor")
            checked += 1
        }
        XCTAssertEqual(checked, EntityType.allCases.count, "graph.js typeColors should name every EntityType")
    }
}
