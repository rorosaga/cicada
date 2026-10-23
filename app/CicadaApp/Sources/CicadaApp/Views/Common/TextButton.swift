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
    /// Looks pass (2026-10-23): a text button that starts a column — Back, "Use an API key", "Not you? Change" —
    /// sets its words on the column's leading edge, as the text above it does; the hover fill still reaches past
    /// them by the same inset. Without it the words sit 6–10 pt in from everything else in the column.
    var flushLeading = false
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var inset: CGFloat { Self.inset(inline: inline) }

    /// The words' inset inside the hover fill — what `flushLeading` pulls back, and what a host that clips (a scroll
    /// view) reaches out by instead (`WhereToCheckChips`).
    static func inset(inline: Bool) -> CGFloat { CicadaTheme.scaled(inline ? 6 : 10) }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                if let keyHint { KeyHint(keyHint) }
            }
            .font(inline ? CicadaTheme.metaMediumFont : CicadaTheme.bodyFont)
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, inset)
            .frame(height: CicadaTheme.scaled(inline ? 22 : Self.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgSelected : Color.clear))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .padding(.leading, flushLeading ? -inset : 0)
    }
}
