import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G68 §2.7 — the four semantic state colours are mode-aware, exactly like
/// `entityColor`, and no view hardcodes their hexes any more.
final class ThemeTokenTests: XCTestCase {

    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private func rgb(_ color: Color) -> [CGFloat] {
        guard let ns = NSColor(color).usingColorSpace(.sRGB) else { return [] }
        return [ns.redComponent, ns.greenComponent, ns.blueComponent]
    }

    private func token(_ name: String, _ read: () -> Color) -> (dark: [CGFloat], light: [CGFloat]) {
        CicadaTheme.mode = .dark
        let dark = rgb(read())
        CicadaTheme.mode = .light
        let light = rgb(read())
        return (dark, light)
    }

    func testEverySemanticTokenHasADistinctValuePerMode() {
        let tokens: [(String, () -> Color)] = [
            ("success", { CicadaTheme.success }),
            ("warning", { CicadaTheme.warning }),
            ("danger", { CicadaTheme.danger }),
            ("info", { CicadaTheme.info }),
            ("codeBackground", { CicadaTheme.codeBackground }),
        ]
        for (name, read) in tokens {
            let (dark, light) = token(name, read)
            XCTAssertEqual(dark.count, 3, name)
            XCTAssertNotEqual(dark, light, "\(name) is the same colour in both modes")
        }
    }

    /// The four state hues must stay distinguishable from each other in BOTH
    /// modes — a "success" that reads as the "warning" hue is worse than a
    /// raw hex.
    func testStateTokensAreDistinctFromEachOtherInBothModes() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let hues = [rgb(CicadaTheme.success), rgb(CicadaTheme.warning),
                        rgb(CicadaTheme.danger), rgb(CicadaTheme.info)]
            for i in hues.indices {
                for j in hues.indices where j > i {
                    XCTAssertNotEqual(hues[i], hues[j], "\(mode.rawValue): tokens \(i) and \(j) collide")
                }
            }
        }
    }

    func testHistoryColorMapsEveryChangeTypeToAStateToken() {
        CicadaTheme.mode = .dark
        XCTAssertEqual(rgb(CicadaTheme.historyColor(for: .created)), rgb(CicadaTheme.success))
        XCTAssertEqual(rgb(CicadaTheme.historyColor(for: .updated)), rgb(CicadaTheme.info))
        XCTAssertEqual(rgb(CicadaTheme.historyColor(for: .relationAdded)), rgb(CicadaTheme.info))
        XCTAssertEqual(rgb(CicadaTheme.historyColor(for: .statusChange)), rgb(CicadaTheme.warning))
        XCTAssertEqual(rgb(CicadaTheme.historyColor(for: .confidenceChange)), rgb(CicadaTheme.warning))
    }

    /// CI-style grep: the nine state hexes may appear ONLY in the theme file.
    /// Brand hues (OriginPill, provider badges, AgentSetup.brand) are exempt
    /// by construction — they are not in this list.
    func testNoStateHexOutsideTheTheme() throws {
        let banned = ["0x22C55E", "0xEF4444", "0xF59E0B", "0x3B82F6",
                      "0x4A9EFF", "0x8B5CF6", "0x3BD97A", "0x6B7280", "0x999999"]
        for file in try Self.swiftSources() {
            if file.lastPathComponent == "CicadaTheme.swift" { continue }
            let text = try String(contentsOf: file, encoding: .utf8).uppercased()
            for hex in banned {
                XCTAssertFalse(text.contains(hex.uppercased()),
                               "\(file.lastPathComponent) still hardcodes \(hex)")
            }
        }
    }

    /// `Sources/CicadaApp/**/*.swift`, resolved from this test file's own path
    /// so it works from any working directory.
    static func swiftSources() throws -> [URL] {
        let testFile = URL(fileURLWithPath: #filePath)
        let packageRoot = testFile
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
        let sources = packageRoot.appendingPathComponent("Sources/CicadaApp")
        guard let walker = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil) else { return [] }
        return walker.compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" }
    }
}
