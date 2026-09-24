import SwiftUI

/// DR-44 — the one pill: 11 medium `textSecondary` on a `bgSelected` capsule, 18 pt tall, tabular.
/// A colour variant adds a 6 pt dot INSIDE the pill and never tints the pill. Never a filter, never
/// mono. The option rows' ages are this (DR-42).
struct Tag: View {
    static let height: CGFloat = 18
    static let dotSize: CGFloat = 6

    let text: String
    var dot: Color? = nil

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(5)) {
            if let dot {
                Circle().fill(dot).frame(width: CicadaTheme.scaled(Self.dotSize), height: CicadaTheme.scaled(Self.dotSize))
            }
            Text(text).monospacedDigit()
        }
        .font(CicadaTheme.font(size: 11, weight: .medium))
        .foregroundStyle(CicadaTheme.textSecondary)
        .padding(.horizontal, CicadaTheme.scaled(7))
        .frame(height: CicadaTheme.scaled(Self.height))
        .background(Capsule().fill(CicadaTheme.bgSelected))
    }
}
