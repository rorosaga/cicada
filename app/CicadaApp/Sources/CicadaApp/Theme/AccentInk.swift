import AppKit
import SwiftUI

/// The accent's ink for text — links and "Recommended" (DR-5 uses 5–6; R-DS4).
///
/// DR-4 makes the accent the Mac's own, so it is whatever the person chose in System Settings.
/// The rules' table spells the text ink for ONE accent, the default blue: the accent itself in
/// dark (5.1:1 on `bgBase`) and 20 % darker in light (`#0062CC`, 5.4:1), because `#007AFF` is
/// only 3.7:1 there. For that blue this returns exactly those values. For any other accent it walks the same
/// direction in 5 % steps until the ink clears 4.5:1 on `bgBase` — yellow needs 50 % black —
/// so a link is never a colour a reader cannot read. Pure, over 8-bit sRGB, so the table
/// test can pin exact hexes.
enum AccentInk {
    struct RGB: Equatable {
        var r: Int, g: Int, b: Int
        init(r: Int, g: Int, b: Int) { self.r = r; self.g = g; self.b = b }
        init(hex: UInt32) { self.init(r: Int((hex >> 16) & 0xFF), g: Int((hex >> 8) & 0xFF), b: Int(hex & 0xFF)) }
        init(_ ns: NSColor) {
            let c = ns.usingColorSpace(.sRGB) ?? .black
            self.init(r: Int((c.redComponent * 255).rounded()), g: Int((c.greenComponent * 255).rounded()),
                      b: Int((c.blueComponent * 255).rounded()))
        }
        static let white = RGB(r: 255, g: 255, b: 255)
        static let black = RGB(r: 0, g: 0, b: 0)

        func mixed(with other: RGB, by t: Double) -> RGB {
            func m(_ a: Int, _ b: Int) -> Int { Int((Double(a) * (1 - t) + Double(b) * t).rounded()) }
            return RGB(r: m(r, other.r), g: m(g, other.g), b: m(b, other.b))
        }
        func isClose(to other: RGB) -> Bool { abs(r - other.r) <= 2 && abs(g - other.g) <= 2 && abs(b - other.b) <= 2 }
        var nsColor: NSColor { NSColor(srgbRed: CGFloat(r) / 255, green: CGFloat(g) / 255, blue: CGFloat(b) / 255, alpha: 1) }
    }

    /// DESIGN_RULES §3.3's mocked system blue, and its hover values.
    static let systemBlueDark = RGB(hex: 0x0A84FF)
    static let systemBlueLight = RGB(hex: 0x007AFF)
    static let ruleHoverDark = RGB(hex: 0x4DA3FF)
    static let ruleHoverLight = RGB(hex: 0x004FA3)
    static let minimumContrast = 4.5
    /// Whole percents, not a Double step: 0.2 + 6 × 0.05 is 0.5000000000000001, and 255 ×
    /// (1 − that) rounds to 127, one unit off the value a person would compute by hand.
    static let stepPercent = 5
    static let capPercent = 60

    static func text(accent: RGB, mode: AppColorScheme, base: RGB) -> RGB {
        switch mode {
        case .dark: walk(accent, toward: .white, fromPercent: 0, over: base)
        case .light: walk(accent, toward: .black, fromPercent: 20, over: base)
        }
    }

    /// The link's hover. The rules' exact values for the default blue; one more step in the
    /// same direction for anything else.
    static func hover(accent: RGB, mode: AppColorScheme, base: RGB) -> RGB {
        if mode == .dark, accent.isClose(to: systemBlueDark) { return ruleHoverDark }
        if mode == .light, accent.isClose(to: systemBlueLight) { return ruleHoverLight }
        let ink = text(accent: accent, mode: mode, base: base)
        return mode == .dark ? ink.mixed(with: .white, by: 0.27) : ink.mixed(with: .black, by: 0.18)
    }

    private static func walk(_ accent: RGB, toward target: RGB, fromPercent start: Int, over base: RGB) -> RGB {
        var percent = start
        var ink = accent.mixed(with: target, by: Double(percent) / 100)
        while contrast(ink, base) < minimumContrast && percent + stepPercent <= capPercent {
            percent += stepPercent
            ink = accent.mixed(with: target, by: Double(percent) / 100)
        }
        return ink
    }

    /// WCAG 2.x, the formula `ThemeTokenTests.contrast` uses.
    static func contrast(_ a: RGB, _ b: RGB) -> Double {
        func lum(_ c: RGB) -> Double {
            func ch(_ v: Int) -> Double { let s = Double(v) / 255; return s <= 0.03928 ? s / 12.92 : pow((s + 0.055) / 1.055, 2.4) }
            return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b)
        }
        let (x, y) = (lum(a), lum(b))
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }

    // MARK: - The live accent

    /// The system accent as `dark`/light draws it — resolved under a FIXED appearance so the
    /// token depends on Cicada's mode, not on whatever appearance happens to be current.
    static func systemAccent(dark: Bool) -> RGB {
        var rgb = dark ? systemBlueDark : systemBlueLight
        NSAppearance(named: dark ? .darkAqua : .aqua)?.performAsCurrentDrawingAppearance {
            rgb = RGB(NSColor.controlAccentColor)
        }
        return rgb
    }

    /// A dynamic colour: its provider re-reads the Mac's accent at every draw, so a change in
    /// System Settings reaches the next frame with no observer to keep (R-DS4).
    static func dynamic(dark: Bool, hover: Bool) -> Color {
        Color(nsColor: NSColor(name: nil) { _ in
            let base = RGB(CicadaTheme.windowBackground(for: dark ? .dark : .light))
            let accent = systemAccent(dark: dark)
            let mode: AppColorScheme = dark ? .dark : .light
            return (hover ? AccentInk.hover(accent: accent, mode: mode, base: base)
                          : AccentInk.text(accent: accent, mode: mode, base: base)).nsColor
        })
    }
    static let textDark = dynamic(dark: true, hover: false)
    static let textLight = dynamic(dark: false, hover: false)
    static let hoverDark = dynamic(dark: true, hover: true)
    static let hoverLight = dynamic(dark: false, hover: true)
}
