import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-2, DR-3, DR-6 — every text token on every surface it is allowed on, both modes. The
/// accent is the Mac's (DR-4), so accent bars are measured on the rules' mocked system blue
/// (`#0A84FF` dark / `#007AFF` light, DESIGN_RULES §3.3); the LIVE accent's text ink is only
/// asserted to clear AA, because the owner's Mac may use any accent (R-DS4).
final class ThemeContrastTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private func c(_ a: Color, _ b: Color) -> Double { ThemeTokenTests.contrast(a, b) }
    private func mockedAccent(_ mode: AppColorScheme) -> AccentInk.RGB {
        AccentInk.RGB(hex: mode == .dark ? 0x0A84FF : 0x007AFF)
    }
    private func base(_ mode: AppColorScheme) -> AccentInk.RGB { AccentInk.RGB(CicadaTheme.windowBackground(for: mode)) }

    func testReadableTextClearsAAOnEverySurfaceItMaySitOn() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let every: [(String, Color)] = [
                ("bgBase", CicadaTheme.bgBase), ("bgPane", CicadaTheme.bgPane), ("bgFocus", CicadaTheme.bgFocus),
                ("bgOption", CicadaTheme.bgOption), ("bgHover", CicadaTheme.bgHover), ("bgSelected", CicadaTheme.bgSelected),
                ("bgButton", CicadaTheme.bgButton), ("bgMenu", CicadaTheme.bgMenu), ("bgRail", CicadaTheme.bgRail),
            ]
            for (s, surface) in every {
                XCTAssertGreaterThanOrEqual(c(CicadaTheme.textPrimary, surface), 4.5, "\(mode.rawValue) textPrimary on \(s)")
                XCTAssertGreaterThanOrEqual(c(CicadaTheme.textSecondary, surface), 4.5, "\(mode.rawValue) textSecondary on \(s)")
                XCTAssertGreaterThanOrEqual(c(CicadaTheme.textTertiaryOnFill, surface), 4.5, "\(mode.rawValue) onFill on \(s)")
            }
            for (s, surface) in every where s != "bgSelected" {
                XCTAssertGreaterThanOrEqual(c(CicadaTheme.textTertiary, surface), 4.5, "\(mode.rawValue) textTertiary on \(s)")
            }
        }
    }

    /// DR-2 — the one pair that needs its own step: light tertiary on a selected fill is 4.33:1.
    func testLightTertiaryOnASelectedFillIsWhyOnFillExists() {
        CicadaTheme.mode = .light
        XCTAssertLessThan(c(CicadaTheme.textTertiary, CicadaTheme.bgSelected), 4.5)
        XCTAssertGreaterThanOrEqual(c(CicadaTheme.textTertiaryOnFill, CicadaTheme.bgSelected), 4.5)
        CicadaTheme.mode = .dark
        XCTAssertGreaterThanOrEqual(c(CicadaTheme.textTertiary, CicadaTheme.bgSelected), 4.5)
    }

    /// DR-3 — quaternary is for disabled controls only: dimmer than tertiary, never the only cue.
    func testQuaternaryIsDimmerThanTertiary() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertLessThan(c(CicadaTheme.textQuaternary, CicadaTheme.bgBase), c(CicadaTheme.textTertiary, CicadaTheme.bgBase))
        }
    }

    /// DR-49 / DR-51 — a keycap's glyph and the rail's numeral are text.
    func testKeycapAndBadgeInk() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.keyGlyph, CicadaTheme.bgKey), 4.5, mode.rawValue)
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.textPrimary, CicadaTheme.bgBadge), 4.5, mode.rawValue)
        }
    }

    /// DR-3 / DR-6 on the mocked blue: a glyph ≥ 3:1; accent TEXT ≥ 4.5:1 on the four surfaces
    /// DR-6 allows; white on the accent fill is 3.6–4.0:1 — legal only at ≥ 13 pt medium on the
    /// one primary button, which is why the rule exists.
    func testTheAccentOnTheRulesMockedBlue() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let accent = mockedAccent(mode)
            let text = AccentInk.text(accent: accent, mode: mode, base: base(mode))
            XCTAssertGreaterThanOrEqual(AccentInk.contrast(accent, base(mode)), 3, "\(mode.rawValue) accent glyph")
            for surface in [CicadaTheme.bgBase, CicadaTheme.bgFocus, CicadaTheme.bgPane, CicadaTheme.bgOption] {
                XCTAssertGreaterThanOrEqual(AccentInk.contrast(text, AccentInk.RGB(NSColor(surface))), 4.5, mode.rawValue)
            }
            let white = AccentInk.contrast(AccentInk.RGB(hex: 0xFFFFFF), accent)
            XCTAssertTrue((3.5..<4.5).contains(white), "\(mode.rawValue) white on accent \(white)")
        }
    }

    /// R-DS4 — whatever accent this Mac has, the link ink clears AA on the base.
    func testTheLiveAccentTextAlwaysReads() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.accentText, CicadaTheme.bgBase), 4.5, mode.rawValue)
        }
    }

    /// §3.8 — the Projects band's fill is a graphical object (≥ 3:1) on the base and on its track.
    func testProgressFill() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.progressFill, CicadaTheme.bgBase), 3, mode.rawValue)
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.progressFill, CicadaTheme.bgBadge), 3, mode.rawValue)
        }
    }

    /// Moved from ThemeTokenTests (G137 R9 §5.1): the four text-safe nature tokens still clear
    /// AA on the new base, and the highlighter wash still carries primary ink.
    func testMeadowsTextSafeTokensOnTheGraphiteBase() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for (name, color) in [("sky", CicadaTheme.sky), ("meadow", CicadaTheme.meadow),
                                  ("dandelion", CicadaTheme.dandelion), ("bark", CicadaTheme.bark)] {
                XCTAssertGreaterThanOrEqual(c(color, CicadaTheme.bgBase), 4.5, "\(mode.rawValue) \(name)")
            }
            let wash = ThemeTokenTests.blend(CicadaTheme.dandelionFill, over: CicadaTheme.surface, alpha: 0.35)
            XCTAssertGreaterThanOrEqual(c(CicadaTheme.textPrimary, wash), 7, "\(mode.rawValue) highlighter wash")
        }
    }
}
