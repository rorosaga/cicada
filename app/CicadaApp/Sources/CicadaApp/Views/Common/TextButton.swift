import SwiftUI

/// DR-40 — the text button: no fill at rest, `bgSelected` on hover, `textSecondary` → `textPrimary`.
/// Not now, Skip, Dismiss, Show all, "‹ 6 questions".
struct TextButton: View {
    static let height: CGFloat = 32

    let title: String
    var keyHint: String? = nil
    var help: String? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                if let keyHint { KeyHint(keyHint) }
            }
            .font(CicadaTheme.font(size: 13))
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgSelected : Color.clear))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
