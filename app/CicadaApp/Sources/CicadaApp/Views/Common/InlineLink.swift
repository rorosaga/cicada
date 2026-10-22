import SwiftUI

/// DR-5 use 5 — a link: 12 medium in `accentText`, no fill, the label's own words (a "›" when it
/// goes to another page). One definition for Needs you's *Open Inbox* and the Sleep menu's
/// "More in Settings → Intelligence ›", so a link is never an ad-hoc `Button` tinted by hand.
/// `accentText` (not the accent) is what clears 4.5:1 in light mode (DR-6).
///
/// Owner 2026-10-14 (Home review #5; DR-41, DR-69): the bare glyph box was a ~15 pt target. The hit area is now 28 pt
/// tall with 6 pt of side slop and a `bgSelected` hover fill on that same shape — **layout-neutral**: the shape grows
/// outside the label's bounds, so a link inside a sentence or a label row keeps its line. The text keeps its look.
struct InlineLink: View {
    let title: String
    var help: String? = nil
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(CicadaTheme.metaMediumFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.accentText)
                .modifier(InlineLinkTarget(hovering: hovering))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// The hit frame around a link's label: at least `HomeTargets.linkHeight` tall and `linkSlop` wider on each side,
/// filled on hover. It is a shape drawn and hit-tested *outside* the label's own bounds (the shape grows from the rect
/// it is given), so the label's layout size never changes.
struct InlineLinkTarget: ViewModifier {
    let hovering: Bool

    func body(content: Content) -> some View {
        let shape = LinkHitShape(minHeight: CicadaTheme.scaled(HomeTargets.linkHeight),
                                 slop: CicadaTheme.scaled(HomeTargets.linkSlop),
                                 radius: CicadaTheme.cornerRadiusSmall)
        content
            .background(shape.fill(hovering ? CicadaTheme.bgSelected : Color.clear))
            .contentShape(shape)
    }
}

/// The label's rect grown to `minHeight` (centred) and by `slop` on each side, with a continuous corner (DR-12).
struct LinkHitShape: Shape {
    let minHeight: CGFloat
    let slop: CGFloat
    let radius: CGFloat

    static func hitRect(for rect: CGRect, minHeight: CGFloat, slop: CGFloat) -> CGRect {
        rect.insetBy(dx: -slop, dy: -max(0, (minHeight - rect.height) / 2))
    }

    func path(in rect: CGRect) -> Path {
        Path(roundedRect: Self.hitRect(for: rect, minHeight: minHeight, slop: slop), cornerRadius: radius,
             style: .continuous)
    }
}
