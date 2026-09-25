import SwiftUI

/// DR-40 — the neutral button: `bgButton` plus a resting ring, `textPrimary` in 13 medium (12 compact),
/// 28 or 32 pt, `cornerRadiusSmall`. Resume, Retry, Submit, Merge, Got it, Keep, Archive, Undo. The
/// Inbox has no primary action, so every answer control that is a button is this one (DR-7: "Keep",
/// "Got it", "Archive" are neutral). It replaces the pre-DS-2 Inbox action button, whose `color`
/// parameter was the P2 problem in one argument.
struct NeutralButton: View {
    enum Size {
        case compact, regular
        var height: CGFloat { self == .compact ? 28 : 32 }
    }

    /// DR-41 — disabled keeps its label, dims to 45 %, and says why in `.help`.
    static let disabledOpacity = 0.45

    let title: String
    var systemImage: String? = nil
    /// A mark before the title — the Sleep page's engine menu wears its engine's (R-HS8). `AnyView?`
    /// so every existing call site stays source-compatible (`PageHeader.leading`'s precedent).
    var leading: AnyView? = nil
    /// A disclosure glyph after the title — a button that opens a menu says so (R-HS10).
    var trailingSystemImage: String? = nil
    var size: Size = .regular
    /// DR-49 — the key that acts, shown where it acts ("⏎" on Submit).
    var keyHint: String? = nil
    var shortcut: KeyboardShortcut? = nil
    var isDisabled = false
    var help: String? = nil
    var disabledHelp: String? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let leading { leading }
                if let systemImage {
                    Image(systemName: systemImage).font(CicadaTheme.icon(.inline))
                }
                // A fixed-height button never wraps: a long engine and model truncates instead.
                Text(title).lineLimit(1).truncationMode(.tail)
                if let keyHint { KeyHint(keyHint) }
                if let trailingSystemImage {
                    Image(systemName: trailingSystemImage)
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .font(CicadaTheme.font(size: size == .compact ? 12 : 13, weight: .medium))
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(size == .compact ? 10 : 12))
            .frame(height: CicadaTheme.scaled(size.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering && !isDisabled ? CicadaTheme.bgButtonHover : CicadaTheme.bgButton))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .keyboardShortcut(shortcut)
        .disabled(isDisabled)
        .opacity(isDisabled ? Self.disabledOpacity : 1)
        .help(isDisabled ? (disabledHelp ?? help ?? title) : (help ?? title))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
