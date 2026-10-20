import SwiftUI

/// DR-48 (consistency pass, round 2, 2026-10-20) — a list row's one fill: `bgSelected` while it is open or current,
/// `bgHover` under the pointer, nothing otherwise, in a `cornerRadiusSmall` shape. About twenty-five rows spelled this
/// by hand, three ways: selected over hover, hover over selected (look-it-up rows), and some easing the change while
/// most snapped. Now one rule, and one motion: only the POINTER's hover eases, on `CicadaMotion.hover`; a selection
/// moved by a key is never animated (DR-60), because the animation is keyed on the hover value alone. A key never
/// hovers — `onHover` is the pointer's.
enum RowFill {
    static func color(selected: Bool, hovering: Bool) -> Color {
        selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)
    }
}

/// The fill alone, for a row whose hover is tracked elsewhere (a parent that knows which row is under the pointer, or
/// a row that also shows controls on hover).
struct RowHoverFill: ViewModifier {
    let hovering: Bool
    var selected = false
    var cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.background {
            CicadaTheme.shape(cornerRadius)
                .fill(RowFill.color(selected: selected, hovering: hovering))
                .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        }
    }
}

/// The fill and the pointer's hover in one: the row hands over its `hovering` state (it may read it for its own
/// words or controls) and this tracks it. `enabled: false` keeps a row that opens nothing from lighting up.
struct RowHover: ViewModifier {
    @Binding var hovering: Bool
    var selected = false
    var enabled = true
    var cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall

    func body(content: Content) -> some View {
        content
            .modifier(RowHoverFill(hovering: hovering && enabled, selected: selected, cornerRadius: cornerRadius))
            .onHover { hovering = $0 }
    }
}

extension View {
    /// DR-48 — the shared row fill; the row tracks its own hover (see `RowHover`).
    func rowHover(_ hovering: Binding<Bool>, selected: Bool = false, enabled: Bool = true,
                  cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall) -> some View {
        modifier(RowHover(hovering: hovering, selected: selected, enabled: enabled, cornerRadius: cornerRadius))
    }

    /// DR-48 — the shared row fill for a hover tracked elsewhere.
    func rowHoverFill(hovering: Bool, selected: Bool = false,
                      cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall) -> some View {
        modifier(RowHoverFill(hovering: hovering, selected: selected, cornerRadius: cornerRadius))
    }
}
