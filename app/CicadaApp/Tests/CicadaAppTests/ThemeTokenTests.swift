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

    /// DESIGN_RULES §3.1–3.2, §3.8 (DR-1, DR-2): every token, both modes, exactly as the
    /// rules' table spells it. The pre-D names are aliases (R-DS2), so they are pinned too — a
    /// caller that still reads `surface` must get the focus surface, not a stale Meadow tint.
    /// Changing one is a design decision: edit this table in the same commit, on purpose.
    func testGraphiteTokensAreTheRulesValues() {
        let rows: [Row] = [
            Row(name: "bgRail", read: { CicadaTheme.bgRail }, dark: 0x0C0D0E, light: 0xEFEFEC),
            Row(name: "bgBase", read: { CicadaTheme.bgBase }, dark: 0x111213, light: 0xF7F7F5),
            Row(name: "background", read: { CicadaTheme.background }, dark: 0x111213, light: 0xF7F7F5),
            Row(name: "bgPane", read: { CicadaTheme.bgPane }, dark: 0x141517, light: 0xFBFBFA),
            Row(name: "bgHover", read: { CicadaTheme.bgHover }, dark: 0x1B1C1E, light: 0xEFEFEC),
            Row(name: "surfaceHover", read: { CicadaTheme.surfaceHover }, dark: 0x1B1C1E, light: 0xEFEFEC),
            Row(name: "bgFocus", read: { CicadaTheme.bgFocus }, dark: 0x18191B, light: 0xFFFFFF),
            Row(name: "surfaceElevated", read: { CicadaTheme.surfaceElevated }, dark: 0x18191B, light: 0xFFFFFF),
            Row(name: "surface", read: { CicadaTheme.surface }, dark: 0x18191B, light: 0xFFFFFF),
            Row(name: "bgOption", read: { CicadaTheme.bgOption }, dark: 0x1D1E21, light: 0xF7F7F5),
            Row(name: "bgButton", read: { CicadaTheme.bgButton }, dark: 0x232427, light: 0xF2F2F0),
            Row(name: "bgButtonHover", read: { CicadaTheme.bgButtonHover }, dark: 0x2C2D30, light: 0xE3E3E0),
            Row(name: "bgSelected", read: { CicadaTheme.bgSelected }, dark: 0x222326, light: 0xE8E8E5),
            Row(name: "bgMenu", read: { CicadaTheme.bgMenu }, dark: 0x1B1C1E, light: 0xFFFFFF),
            Row(name: "bgKey", read: { CicadaTheme.bgKey }, dark: 0x26272A, light: 0xEAEAE7),
            Row(name: "keyGlyph", read: { CicadaTheme.keyGlyph }, dark: 0x9A9CA1, light: 0x5A5B60),
            Row(name: "bgBadge", read: { CicadaTheme.bgBadge }, dark: 0x3A3B3F, light: 0xD9D9D6),
            Row(name: "bgRailHover", read: { CicadaTheme.bgRailHover }, dark: 0x1B1C1E, light: 0xE3E3E0),
            Row(name: "commandBarFill", read: { CicadaTheme.commandBarFill }, dark: 0x1B1C1E, light: 0xFFFFFF),
            Row(name: "border", read: { CicadaTheme.border }, dark: 0x222324, light: 0xE3E3E1),
            Row(name: "borderLight", read: { CicadaTheme.borderLight }, dark: 0x323334, light: 0xCFCFCE),
            Row(name: "textPrimary", read: { CicadaTheme.textPrimary }, dark: 0xF5F5F6, light: 0x141415),
            Row(name: "textSecondary", read: { CicadaTheme.textSecondary }, dark: 0xD0D1D4, light: 0x38393C),
            Row(name: "textTertiary", read: { CicadaTheme.textTertiary }, dark: 0x8D8F94, light: 0x6A6B70),
            Row(name: "textTertiaryOnFill", read: { CicadaTheme.textTertiaryOnFill }, dark: 0x8D8F94, light: 0x5E5F64),
            Row(name: "textQuaternary", read: { CicadaTheme.textQuaternary }, dark: 0x6A6C71, light: 0x8A8B90),
            Row(name: "progressFill", read: { CicadaTheme.progressFill }, dark: 0x6FB57B, light: 0x37753D),
            Row(name: "codeBackground", read: { CicadaTheme.codeBackground }, dark: 0x111213, light: 0xF7F7F5),
            // Meadow's nature tokens did not move (DR-13): art and reward moments only.
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
        XCTAssertEqual(CicadaTheme.cornerRadiusSmall, 8)
        XCTAssertEqual(CicadaTheme.cornerRadius, 10, "DR-12 (was 12)")
        XCTAssertEqual(CicadaTheme.radiusLarge, 16, "DR-12 (was 18)")
    }

    /// DR-4 — the accent is the Mac's, in both modes; the ink on it is white (R-DS5, DR-6).
    func testTheAccentIsTheSystemsAndItsInkIsWhite() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertEqual(CicadaTheme.accent, Color.accentColor, mode.rawValue)
            XCTAssertEqual(rgb(CicadaTheme.onAccent), rgb(.white), mode.rawValue)
        }
    }

    /// DR-8 / R-DS6 — the retired indigo is still the "active" status hue and the heat ramp's
    /// top step: data hues do not move when the chrome's accent does.
    func testTheActiveStatusHueDidNotMoveWithTheAccent() {
        CicadaTheme.mode = .dark
        XCTAssertEqual(rgb(CicadaTheme.statusColor(for: .active)), rgb(Color(hex: 0x8C9CFF)))
        XCTAssertEqual(rgb(CicadaTheme.heatRamp(level: 4)), rgb(Color(hex: 0x8C9CFF)))
        CicadaTheme.mode = .light
        XCTAssertEqual(rgb(CicadaTheme.statusColor(for: .active)), rgb(Color(hex: 0x4A5BD6)))
    }

    /// DR-1 — neutrals are graphite: CIE Lab chroma ≤ 4 for every surface and ink. The rule's
    /// "blue exceeds red by at most 3" holds for the window family; the table's own fills
    /// measure 4 (bgBadge 5) and the table wins (R-DS3, DESIGN_RULES §9).
    func testNeutralsAreGraphite() {
        let family: [(String, () -> Color)] = [
            ("bgRail", { CicadaTheme.bgRail }), ("bgBase", { CicadaTheme.bgBase }), ("bgPane", { CicadaTheme.bgPane }),
            ("bgHover", { CicadaTheme.bgHover }), ("bgFocus", { CicadaTheme.bgFocus }), ("bgMenu", { CicadaTheme.bgMenu }),
        ]
        let fills: [(String, () -> Color)] = [
            ("bgOption", { CicadaTheme.bgOption }), ("bgButton", { CicadaTheme.bgButton }),
            ("bgButtonHover", { CicadaTheme.bgButtonHover }), ("bgSelected", { CicadaTheme.bgSelected }),
            ("bgKey", { CicadaTheme.bgKey }), ("bgBadge", { CicadaTheme.bgBadge }),
        ]
        let inks: [(String, () -> Color)] = [
            ("textPrimary", { CicadaTheme.textPrimary }), ("textSecondary", { CicadaTheme.textSecondary }),
            ("textTertiary", { CicadaTheme.textTertiary }), ("textQuaternary", { CicadaTheme.textQuaternary }),
            ("keyGlyph", { CicadaTheme.keyGlyph }), ("border", { CicadaTheme.border }), ("borderLight", { CicadaTheme.borderLight }),
        ]
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for (name, read) in family + fills + inks {
                XCTAssertLessThanOrEqual(Self.chroma(read()), 4, "\(mode.rawValue) \(name) is tinted")
            }
        }
        CicadaTheme.mode = .dark
        func blueOverRed(_ c: Color) -> Int { let v = rgb(c).map { Int(($0 * 255).rounded()) }; return v[2] - v[0] }
        for (name, read) in family { XCTAssertLessThanOrEqual(blueOverRed(read()), 3, name) }
        for (name, read) in fills { XCTAssertLessThanOrEqual(blueOverRed(read()), 5, name) }
    }

    /// CIE L*a*b* chroma (D65) — DR-1's "LCH chroma".
    static func chroma(_ color: Color) -> Double {
        guard let ns = NSColor(color).usingColorSpace(.sRGB) else { return .infinity }
        func lin(_ v: CGFloat) -> Double {
            let v = Double(v)
            return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
        }
        let (r, g, b) = (lin(ns.redComponent), lin(ns.greenComponent), lin(ns.blueComponent))
        let x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
        let y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        let z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
        func f(_ t: Double) -> Double { t > 0.008856 ? cbrt(t) : 7.787 * t + 16.0 / 116.0 }
        let a = 500 * (f(x) - f(y)), bb = 200 * (f(y) - f(z))
        return (a * a + bb * bb).squareRoot()
    }

    /// Keeps the Light-palette comment honest: it used to promise ~4.5:1 for
    /// every light entity hue, and skill measured 2.93. Deepening a hue is a
    /// data-colour decision graph.js must match — do it, then move it here.
    func testLightEntityHueContrastIsWhatTheThemeCommentSays() {
        CicadaTheme.mode = .light
        let bg = CicadaTheme.background
        func c(_ t: EntityType) -> Double { Self.contrast(CicadaTheme.entityColor(for: t), bg) }
        for t in [EntityType.person, .project, .directory, .location] {
            XCTAssertGreaterThanOrEqual(c(t), 4.5, "\(t.rawValue) is documented as text-safe")
        }
        for t in [EntityType.media, .deadline, .hub, .tool, .concept, .company] {
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

    /// Track I T4 (D-4) — the meadow pill's ink clears AA on the meadow in both
    /// modes: white on the day meadow, night-meadow ink on the night meadow.
    func testTheMeadowPillInkClearsAA() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.onMeadow, CicadaTheme.meadow), 4.5, mode.rawValue)
        }
    }

    /// The overlay scrim dims harder in dark, where 0.4 over a near-black window reads as nothing.
    func testTheScrimDimsHarderInDark() {
        CicadaTheme.mode = .dark
        let dark = NSColor(CicadaTheme.scrim).alphaComponent
        CicadaTheme.mode = .light
        let light = NSColor(CicadaTheme.scrim).alphaComponent
        XCTAssertGreaterThan(dark, light)
        XCTAssertEqual(Double(light), 0.35, accuracy: 0.001)
        CicadaTheme.mode = .dark
        XCTAssertEqual(Double(NSColor(CicadaTheme.scrimPanel).alphaComponent), 0.24, accuracy: 0.001)
        CicadaTheme.mode = .light
        XCTAssertEqual(Double(NSColor(CicadaTheme.scrimPanel).alphaComponent), 0.12, accuracy: 0.001, "DR-33")
    }
}
