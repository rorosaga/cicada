import SwiftUI

/// The one icon-only button (DR-40, DR-53, DR-69): a 28 × 28 hit area, a 14 pt glyph (16 in the
/// titlebar), `textTertiary` at rest and `textPrimary` on a `bgSelected` hover. `help` is not
/// optional: an icon-only control always says what it does and its shortcut, in `.help` and to
/// VoiceOver.
struct IconButton: View {
    enum Size {
        case titlebar, inline
        var role: CicadaTheme.IconRole { self == .titlebar ? .titlebar : .list }
    }

    let systemName: String
    let help: String
    var accessibilityLabel: String? = nil
    var size: Size = .inline
    var shortcut: KeyboardShortcut? = nil
    /// `isOn` — a sticky toggle (the Graph's pan button, R-DG3) wears the selected fill, never the accent (DR-5).
    var isOn = false
    /// What an assistive technology's press runs instead of `action` (VoiceOver's VO-Space, Switch Control): nil runs
    /// `action`. A caller that reads the event running its action to choose its motion (DR-60) passes one, because an
    /// accessibility press arrives with no event of its own — `NSApp.currentEvent` is whatever came last, often a
    /// click — and must land as a key does (`AssistivePress`).
    var accessibilityPress: (() -> Void)? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(CicadaTheme.icon(size.role))
                .foregroundStyle(hovering || isOn ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .iconHover(hovering: hovering)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering || isOn ? CicadaTheme.bgSelected : Color.clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .keyboardShortcut(shortcut)
        .help(help)
        .accessibilityLabel(accessibilityLabel ?? help)
        .accessibilityAddTraits(isOn ? .isSelected : [])
        .modifier(AssistivePress(action: accessibilityPress))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// An assistive technology's press, set apart from the pointer's and the keyboard's (2026-10-20, DR-60): with an
/// action, the view's default accessibility action runs it instead of the control's own; with none, nothing changes.
struct AssistivePress: ViewModifier {
    let action: (() -> Void)?

    func body(content: Content) -> some View {
        if let action {
            content.accessibilityAction(.default, action)
        } else {
            content
        }
    }
}
