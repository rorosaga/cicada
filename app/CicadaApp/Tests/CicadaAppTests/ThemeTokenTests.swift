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

    // MARK: - G137 Meadow (spec R-M1/R-M2; plan R-M8 … R-M11)

    /// WCAG 2.x contrast between two opaque colours — the formula R9 §5.1's
    /// table was computed with, so the bars below are the table's own numbers.
    static func contrast(_ a: Color, _ b: Color) -> Double {
        func luminance(_ c: Color) -> Double {
            guard let ns = NSColor(c).usingColorSpace(.sRGB) else { return 0 }
            func channel(_ v: CGFloat) -> Double {
                let v = Double(v)
                return v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
            }
            return 0.2126 * channel(ns.redComponent) + 0.7152 * channel(ns.greenComponent)
                + 0.0722 * channel(ns.blueComponent)
        }
        let (x, y) = (luminance(a), luminance(b))
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }

    /// `fg` at `alpha` over an opaque `bg` — where a 35 % highlighter wash
    /// actually lands under a word.
    static func blend(_ fg: Color, over bg: Color, alpha: Double) -> Color {
        let f = NSColor(fg).usingColorSpace(.sRGB)!, b = NSColor(bg).usingColorSpace(.sRGB)!
        func mix(_ x: CGFloat, _ y: CGFloat) -> Double { Double(x) * alpha + Double(y) * (1 - alpha) }
        return Color(.sRGB, red: mix(f.redComponent, b.redComponent),
                     green: mix(f.greenComponent, b.greenComponent),
                     blue: mix(f.blueComponent, b.blueComponent))
    }

    private struct Row {
        let name: String
        let read: () -> Color
        let dark: UInt32
        let light: UInt32
    }

    /// Every Meadow token, both modes, exactly as the spec's table spells it.
    /// Changing one is a design decision: edit this table in the same commit,
    /// on purpose.
    func testMeadowTokensAreTheRulingsValues() {
        let rows: [Row] = [
            Row(name: "background", read: { CicadaTheme.background }, dark: 0x0D1216, light: 0xF4F6F1),
            Row(name: "surface", read: { CicadaTheme.surface }, dark: 0x141A1F, light: 0xFFFFFF),
            Row(name: "surfaceHover", read: { CicadaTheme.surfaceHover }, dark: 0x1A2227, light: 0xECF0E8),
            Row(name: "surfaceElevated", read: { CicadaTheme.surfaceElevated }, dark: 0x20292F, light: 0xFFFFFF),
            Row(name: "border", read: { CicadaTheme.border }, dark: 0x25303A, light: 0xDFE4D9),
            Row(name: "borderLight", read: { CicadaTheme.borderLight }, dark: 0x35424D, light: 0xC5CCBC),
            Row(name: "textPrimary", read: { CicadaTheme.textPrimary }, dark: 0xE8EEE9, light: 0x1B1F1A),
            Row(name: "textSecondary", read: { CicadaTheme.textSecondary }, dark: 0x9CA8A0, light: 0x4C5548),
            Row(name: "textTertiary", read: { CicadaTheme.textTertiary }, dark: 0x6E7A73, light: 0x767E70),
            Row(name: "accent", read: { CicadaTheme.accent }, dark: 0x8C9CFF, light: 0x4A5BD6),
            Row(name: "onAccent", read: { CicadaTheme.onAccent }, dark: 0x0D1216, light: 0xFFFFFF),
            Row(name: "codeBackground", read: { CicadaTheme.codeBackground }, dark: 0x0A0E11, light: 0xE8ECE3),
            Row(name: "sky", read: { CicadaTheme.sky }, dark: 0x8EC3F0, light: 0x3571B0),
            Row(name: "skyWash", read: { CicadaTheme.skyWash }, dark: 0x1A2B3D, light: 0xD7E8F5),
            Row(name: "meadow", read: { CicadaTheme.meadow }, dark: 0x7FC98A, light: 0x37753D),
            Row(name: "meadowWash", read: { CicadaTheme.meadowWash }, dark: 0x1B2B22, light: 0xDCEBD6),
            Row(name: "dandelion", read: { CicadaTheme.dandelion }, dark: 0xF6CF5A, light: 0x8A6400),
            Row(name: "dandelionFill", read: { CicadaTheme.dandelionFill }, dark: 0xD9A92E, light: 0xF5C542),
            Row(name: "cloud", read: { CicadaTheme.cloud }, dark: 0xC9D3DE, light: 0xFFFFFF),
            Row(name: "bark", read: { CicadaTheme.bark }, dark: 0xB89C86, light: 0x6B5344),
            Row(name: "soil", read: { CicadaTheme.soil }, dark: 0x2A221E, light: 0x3B2F2A),
        ]
        for row in rows {
            let got = token(row.name, row.read)
            XCTAssertEqual(got.dark, rgb(Color(hex: row.dark)), "\(row.name) (dark)")
            XCTAssertEqual(got.light, rgb(Color(hex: row.light)), "\(row.name) (light)")
            XCTAssertNotEqual(got.dark, got.light, "\(row.name) is the same colour in both modes")
        }
        XCTAssertEqual(CicadaTheme.radiusXS, 4)
        XCTAssertEqual(CicadaTheme.radiusLarge, 18)
    }

    /// The contrast table (R9 §5.1) as bars, both modes. Measured values on
    /// this base: textPrimary 15.99 / 15.35, textSecondary 7.64 / 7.15,
    /// accent 7.46 / 5.13, onAccent-on-accent 7.46 / 5.59, highlighter wash
    /// 7.18 / 14.1 (dark / light).
    func testTheMeadowContrastBarsHold() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let bg = CicadaTheme.background
            let m = mode.rawValue
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, bg), 15, "\(m) textPrimary")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textSecondary, bg), 7, "\(m) textSecondary")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.accent, bg), 5, "\(m) accent")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.onAccent, CicadaTheme.accent), 4.5,
                                        "\(m) onAccent on accent")
            let textSafe: [(String, Color)] = [("sky", CicadaTheme.sky), ("meadow", CicadaTheme.meadow),
                                               ("dandelion", CicadaTheme.dandelion), ("bark", CicadaTheme.bark)]
            for (name, color) in textSafe {
                XCTAssertGreaterThanOrEqual(Self.contrast(color, bg), 4.5, "\(m) \(name) is sold as text-safe")
            }
            let wash = Self.blend(CicadaTheme.dandelionFill, over: CicadaTheme.surface, alpha: 0.35)
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, wash), 7, "\(m) highlighter wash")
        }
    }

    /// Keeps the Light-palette comment honest: it used to promise ~4.5:1 for
    /// every light entity hue, and skill measured 2.93. Deepening a hue is a
    /// data-colour decision graph.js must match — do it, then move it here.
    func testLightEntityHueContrastIsWhatTheThemeCommentSays() {
        CicadaTheme.mode = .light
        let bg = CicadaTheme.background
        func c(_ t: EntityType) -> Double { Self.contrast(CicadaTheme.entityColor(for: t), bg) }
        for t in [EntityType.person, .project, .directory] {
            XCTAssertGreaterThanOrEqual(c(t), 4.5, "\(t.rawValue) is documented as text-safe")
        }
        for t in [EntityType.location, .media, .deadline, .hub, .tool, .concept, .company] {
            XCTAssertTrue((3.0..<4.5).contains(c(t)), "\(t.rawValue) \(c(t)) is documented as non-text only")
        }
        XCTAssertLessThan(c(.skill), 3.0, "skill is documented as clearing neither bar")
    }

    func testSkyGradientsAreTheRulingsStopsAndKeepTextLegible() {
        XCTAssertEqual(CicadaTheme.skyGradient(.day).map { rgb($0) },
                       [0xB9D7F0, 0xE9F2F6].map { rgb(Color(hex: $0)) })
        XCTAssertEqual(CicadaTheme.skyGradient(.dusk).map { rgb($0) },
                       [0x1C2344, 0x3A3A6A, 0x7A5E7E].map { rgb(Color(hex: $0)) })
        XCTAssertEqual(CicadaTheme.skyGradient(.night).map { rgb($0) },
                       [0x0A0F1E, 0x172538].map { rgb(Color(hex: $0)) })
        CicadaTheme.mode = .light
        XCTAssertEqual(CicadaTheme.SkyPhase.current, .day)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.day)[0]), 11)
        CicadaTheme.mode = .dark
        XCTAssertEqual(CicadaTheme.SkyPhase.current, .night)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.dusk)[2]), 4.5)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.night)[1]), 13)
    }

    func testTheWindowBackgroundIsTheBackgroundToken() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let window = CicadaTheme.windowBackground(for: mode).usingColorSpace(.sRGB)!
            XCTAssertEqual([window.redComponent, window.greenComponent, window.blueComponent],
                           rgb(CicadaTheme.background), mode.rawValue)
        }
    }

    /// The window's RGB was hand-copied from the old neutrals — the copy is
    /// what would have left a violet titlebar over a meadow page (R-M10).
    func testNoWindowColourIsHandCopied() throws {
        for file in try Self.swiftSources() where file.lastPathComponent != "CicadaTheme.swift" {
            XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("NSColor(red:"),
                           "\(file.lastPathComponent) hand-copies a colour into AppKit — "
                           + "read CicadaTheme.windowBackground(for:) (G137 R-M10)")
        }
    }
}
