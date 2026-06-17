import SwiftUI

enum CicadaTheme {
    // MARK: - Background & Surface
    static let background = Color(hex: 0x1A1A1A)
    static let surface = Color(hex: 0x222222)
    static let surfaceHover = Color(hex: 0x2A2A2A)
    static let surfaceElevated = Color(hex: 0x2E2E2E)
    static let border = Color(hex: 0x333333)
    static let borderLight = Color(hex: 0x444444)

    // MARK: - Text
    static let textPrimary = Color(hex: 0xF5F5F5)
    static let textSecondary = Color(hex: 0x999999)
    static let textTertiary = Color(hex: 0x666666)

    // MARK: - Accent
    static let accent = Color(hex: 0x7C8FFF)

    // MARK: - Entity Type Colors
    // Mirrors the `typeColors` map in graph.js so the SwiftUI chrome and the d3
    // canvas agree on hue per type.
    static func entityColor(for type: EntityType) -> Color {
        switch type {
        case .person: Color(hex: 0x4A9EFF)
        case .project: Color(hex: 0xA855F7)
        case .company: Color(hex: 0xF97316)
        case .concept: Color(hex: 0x22C55E)
        case .tool: Color(hex: 0x14B8A6)
        case .deadline: Color(hex: 0xEF4444)
        case .skill: Color(hex: 0xEAB308)
        case .location: Color(hex: 0x9CA3AF)
        case .media: mediaPink
        case .hub: hubGold
        case .unknown: Color(hex: 0x999999)
        }
    }

    // MARK: - Graph-specific accents
    static let mediaPink = Color(hex: 0xEC4899)   // media entity hue
    static let hubGold = Color(hex: 0xE6B450)     // hub ring / hub node hue
    static let pendingPulse = Color(hex: 0xF5C04E) // amber "needs you" pulse

    // MARK: - Context Colors (claim layer)
    // Contexts are an open set, so we hash unknown ones into a stable hue and
    // hard-code the known core to keep the demo legible. Mirrored by
    // CONTEXT_COLORS in graph.js for the d3 canvas.
    static func contextColor(_ context: String) -> Color {
        switch context {
        case "engineering":   return Color(hex: 0x14B8A6)   // teal
        case "family":        return Color(hex: 0xEC4899)   // pink
        case "philosophical": return Color(hex: 0xA855F7)   // purple
        case "career":        return Color(hex: 0xF97316)   // orange
        case "cross":         return Color(hex: 0xEAB308)   // gold — the cross-context bridge
        case "general":       return Color(hex: 0x6B7280)   // gray
        default:
            // Stable hue for any open-tail context so the graph never flickers.
            // Mirrors graph.js `hashHue` (h = h*31 + charCode, 32-bit wrap, then
            // abs % 360) and its `hsl(hue, 55%, 65%)` output EXACTLY so the
            // SwiftUI chrome and the d3 canvas pick the same color for an
            // unknown context. NOTE: Swift's String.hashValue is per-process
            // randomized — never use it for a color that must be stable.
            let hue = Double(hashHue(context))
            return Color(hslHue: hue, saturation: 0.55, lightness: 0.65)
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
        case .decaying: Color(hex: 0xF59E0B)
        case .archived: Color(hex: 0x6B7280)
        case .dropped: Color(hex: 0xEF4444).opacity(0.6)
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
        case .decay: Color(hex: 0xF59E0B)
        case .conflict: Color(hex: 0xEF4444)
        case .clarification: Color(hex: 0x7C8FFF)
        case .mergeSuggestion: Color(hex: 0xEAB308)
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
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.3), radius: 20, y: 10)
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
