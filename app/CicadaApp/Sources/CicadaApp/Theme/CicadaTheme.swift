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
}
