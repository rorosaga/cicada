import SwiftUI

enum CicadaTheme {
    // MARK: - Background & Surface
    // Radix-style 4-step elevation ramp on a Catppuccin/Tokyo-Night cool
    // near-black base with a faint violet cast. Darkening the canvas is the
    // single biggest "pop" lever since the d3 graph is transparent and every
    // node sits directly on `background`.
    static let background = Color(hex: 0x0E0F14)
    static let surface = Color(hex: 0x16171D)
    static let surfaceHover = Color(hex: 0x1D1F26)
    static let surfaceElevated = Color(hex: 0x23252E)
    static let border = Color(hex: 0x262A33)
    static let borderLight = Color(hex: 0x363B47)

    // MARK: - Text
    // AA-checked against the darkest surface (#0E0F14). Primary ~16.5:1 (AAA),
    // secondary ~6.9:1 (AA), tertiary ~3.6:1 (decorative/large only).
    static let textPrimary = Color(hex: 0xECEDF2)
    static let textSecondary = Color(hex: 0x9BA1AE)
    static let textTertiary = Color(hex: 0x6B7180)

    // MARK: - Accent
    // Periwinkle, nudged one notch brighter so it pops on the darker base.
    static let accent = Color(hex: 0x8896FF)

    // MARK: - Entity Type Colors
    // Mirrors the `typeColors` map in graph.js so the SwiftUI chrome and the d3
    // canvas agree on hue per type.
    static func entityColor(for type: EntityType) -> Color {
        // Tailwind-400-band hues: each keeps its type identity but is pushed
        // brighter/more saturated so all 8 clear ~4.5:1+ on the darker base and
        // stay >15° apart in hue. MUST stay in sync with graph.js `typeColors`.
        switch type {
        case .person: Color(hex: 0x5AA8FF)
        case .project: Color(hex: 0xB57BFF)
        case .company: Color(hex: 0xFF8A3D)
        case .concept: Color(hex: 0x3BD97A)
        case .tool: Color(hex: 0x2DD4BF)
        case .deadline: Color(hex: 0xFF5C5C)
        case .skill: Color(hex: 0xF2C744)
        case .location: Color(hex: 0xAEB6C4)
        case .media: mediaPink
        case .hub: hubGold
        case .unknown: Color(hex: 0x9BA1AE)
        }
    }

    // MARK: - Graph-specific accents
    static let mediaPink = Color(hex: 0xF65BA6)   // media entity hue
    static let hubGold = Color(hex: 0xE0A93A)     // hub ring / hub node hue (deeper amber, distinct from skill gold)
    static let pendingPulse = Color(hex: 0xFFCB57) // amber "needs you" pulse

    // MARK: - Context Colors (claim layer)
    // Contexts are an open set, so we hash unknown ones into a stable hue and
    // hard-code the known core to keep the demo legible. Mirrored by
    // CONTEXT_COLORS in graph.js for the d3 canvas.
    static func contextColor(_ context: String) -> Color {
        switch context {
        case "engineering":   return Color(hex: 0x2DD4BF)   // teal  = tool
        case "family":        return Color(hex: 0xF65BA6)   // pink  = media
        case "philosophical": return Color(hex: 0xB57BFF)   // purple = project
        case "career":        return Color(hex: 0xFF8A3D)   // orange = company
        case "cross":         return Color(hex: 0xF2C744)   // gold — the cross-context bridge (= skill)
        case "general":       return Color(hex: 0x7A8290)   // neutral, lifted to stay visible on the dark base
        default:
            // Stable hue for any open-tail context so the graph never flickers.
            // Mirrors graph.js `hashHue` (h = h*31 + charCode, 32-bit wrap, then
            // abs % 360) and its `hsl(hue, 55%, 68%)` output EXACTLY so the
            // SwiftUI chrome and the d3 canvas pick the same color for an
            // unknown context. NOTE: Swift's String.hashValue is per-process
            // randomized — never use it for a color that must be stable.
            let hue = Double(hashHue(context))
            return Color(hslHue: hue, saturation: 0.55, lightness: 0.68)
        }
    }

    /// Deterministic 0–359 hue for an open-tail context string. Byte-for-byte
    /// match of graph.js `hashHue`: 32-bit signed wraparound on each step.
    private static func hashHue(_ str: String) -> Int {
        var h: Int32 = 0
        for scalar in str.unicodeScalars {
            // charCodeAt() yields UTF-16 code units; restrict to BMP like JS
            // does for the demo's ASCII context labels.
            h = h &* 31 &+ Int32(truncatingIfNeeded: scalar.value)
        }
        return Int(abs(Int(h)) % 360)
    }

    // MARK: - Status Colors
    static func statusColor(for status: EntityStatus) -> Color {
        switch status {
        case .active: accent
        case .decaying: Color(hex: 0xF5A93B)
        case .archived: Color(hex: 0x7A8290)
        case .dropped: Color(hex: 0xFF5C5C).opacity(0.6)
        }
    }

    // MARK: - Typography
    static let titleFont = Font.system(size: 20, weight: .semibold)
    static let headingFont = Font.system(size: 16, weight: .medium)
    static let bodyFont = Font.system(size: 13, weight: .regular)
    static let captionFont = Font.system(size: 11, weight: .regular)
    static let monoFont = Font.system(size: 12, weight: .regular, design: .monospaced)

    // MARK: - Spacing
    static let spacingXS: CGFloat = 4
    static let spacingSM: CGFloat = 8
    static let spacingMD: CGFloat = 12
    static let spacingLG: CGFloat = 16
    static let spacingXL: CGFloat = 24
    static let spacingXXL: CGFloat = 32

    // MARK: - Corner Radius
    static let cornerRadius: CGFloat = 12
    static let cornerRadiusSmall: CGFloat = 8

    // MARK: - Inbox Kind Colors
    // Leading-icon hue per inbox card kind. Decay amber, conflict red,
    // clarification indigo, merge yellow. Used by InboxCardView and the
    // sidebar/filter chrome.
    static func inboxColor(for kind: InboxKind) -> Color {
        switch kind {
        case .decay: Color(hex: 0xF5A93B)
        case .conflict: Color(hex: 0xFF5C5C)
        case .clarification: Color(hex: 0x8896FF)
        case .mergeSuggestion: Color(hex: 0xF2C744)
        }
    }
}

// MARK: - Glass Card Modifier

struct GlassCard: ViewModifier {
    var cornerRadius: CGFloat = CicadaTheme.cornerRadius

    func body(content: Content) -> some View {
        content
            .background {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(CicadaTheme.surface.opacity(0.6))
            }
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(
                // On the darker base a thin border reads crisper than a heavy
                // glass blur (Linear/GitHub convention). Use the cool `border`
                // token instead of a flat white stroke, and a tighter shadow.
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.3), radius: 14, y: 8)
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = CicadaTheme.cornerRadius) -> some View {
        modifier(GlassCard(cornerRadius: cornerRadius))
    }
}

// MARK: - Color Hex Init

extension Color {
    init(hex: UInt32, opacity: Double = 1.0) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: opacity
        )
    }

    /// HSL initializer so we can match CSS `hsl()` exactly. SwiftUI's stock
    /// `Color(hue:saturation:brightness:)` is HSB, which produces a different
    /// color for the same numbers — graph.js emits `hsl(...)`, so the open-tail
    /// context color must be computed in HSL to agree with the d3 canvas.
    init(hslHue: Double, saturation s: Double, lightness l: Double, opacity: Double = 1.0) {
        let h = (hslHue.truncatingRemainder(dividingBy: 360) + 360)
            .truncatingRemainder(dividingBy: 360) / 360.0
        let c = (1 - abs(2 * l - 1)) * s
        let x = c * (1 - abs((h * 6).truncatingRemainder(dividingBy: 2) - 1))
        let m = l - c / 2
        let (r1, g1, b1): (Double, Double, Double)
        switch h * 6 {
        case ..<1: (r1, g1, b1) = (c, x, 0)
        case ..<2: (r1, g1, b1) = (x, c, 0)
        case ..<3: (r1, g1, b1) = (0, c, x)
        case ..<4: (r1, g1, b1) = (0, x, c)
        case ..<5: (r1, g1, b1) = (x, 0, c)
        default:   (r1, g1, b1) = (c, 0, x)
        }
        self.init(.sRGB, red: r1 + m, green: g1 + m, blue: b1 + m, opacity: opacity)
    }
}
