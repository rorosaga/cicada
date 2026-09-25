import SwiftUI

/// DR-40 — the text button: no fill at rest, `bgSelected` on hover, `textSecondary` → `textPrimary`.
/// Not now, Skip, Dismiss, Show all, "‹ 6 questions".
struct TextButton: View {
    static let height: CGFloat = 32

    let title: String
    var keyHint: String? = nil
    var help: String? = nil
    /// R-FA1 — a text button that sits inside a sentence line of chips; 32 pt would stretch the line. Same kind
    /// (DR-40), only the height and type step down to a participant chip's 22 pt.
    var inline = false
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                if let keyHint { KeyHint(keyHint) }
            }
            .font(inline ? CicadaTheme.font(size: 12, weight: .medium) : CicadaTheme.font(size: 13))
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(inline ? 6 : 10))
            .frame(height: CicadaTheme.scaled(inline ? 22 : Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgSelected : Color.clear))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
