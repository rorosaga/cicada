import SwiftUI

/// A status as a dot and one word (owner, 2026-10-22: "status as a dot + one word"): green when on, the tertiary ink
/// when off — never the accent (DR-5) and never a capsule (DR-51). Used by every connection row: Intelligence, Devices,
/// You's profiles and the Agents page.
struct StatusDot: View {
    let word: String
    var on: Bool

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(5)) {
            Circle()
                .fill(on ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.6))
                .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
            Text(word)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(on ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(word)
    }
}
